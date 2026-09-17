from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tda_companion import diagnostics
from tda_companion.agent_connection import AgentProbe


def _runtime_paths(tmp_path: Path):
    return SimpleNamespace(runtime_root=tmp_path / "Runtime")


def test_agent_diagnostic_uses_verified_connection_truth(monkeypatch):
    observed = {}

    class FakeConnection:
        def __init__(self, token, port, start_agent, *, expected_version):
            observed.update(
                token=token,
                port=port,
                start_agent=start_agent,
                expected_version=expected_version,
            )

        def probe(self, *, timeout):
            observed["timeout"] = timeout
            return AgentProbe(
                "exact",
                {"service_version": diagnostics.VERSION, "pid": 4321, "port": 8765},
            )

    monkeypatch.setattr(diagnostics, "AgentConnection", FakeConnection)

    result = diagnostics._agent_check(8765)

    assert result == {
        "code": "agent",
        "status": "pass",
        "message": "Agent local verificado",
        "detail": f"v{diagnostics.VERSION} · pid 4321",
    }
    assert observed["token"] == ""
    assert observed["expected_version"] == diagnostics.VERSION
    assert observed["timeout"] == 0.5


def test_agent_diagnostic_preserves_owner_verification_failure_code(monkeypatch):
    class FakeConnection:
        def __init__(self, *_args, **_kwargs):
            pass

        def probe(self, *, timeout):
            assert timeout == 0.5
            return AgentProbe(
                "foreign",
                {"service_version": "0.3.4", "pid": 9320, "port": 8765},
                "AGENT_PROCESS_EXECUTABLE_UNVERIFIED",
            )

    monkeypatch.setattr(diagnostics, "AgentConnection", FakeConnection)

    result = diagnostics._agent_check(8765)

    assert result["status"] == "fail"
    assert result["message"] == "Porta local ocupada por processo não verificado"
    assert result["detail"] == "AGENT_PROCESS_EXECUTABLE_UNVERIFIED"


def test_whisper_incompatible_is_reported_as_outdated_not_corrupt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        diagnostics,
        "inspect_whisper_runtime",
        lambda _root, verify_worker: {
            "status": "incompatible",
            "version": "1.1.1",
            "worker": None,
        },
    )

    result = diagnostics._whisper_runtime_check(_runtime_paths(tmp_path))

    assert result["status"] == "fail"
    assert result["message"] == "Runtime Whisper está desatualizado para este Companion"
    assert "instalado v1.1.1" in result["detail"]
    assert f"mínimo v{diagnostics.MIN_COMPATIBLE_WHISPER_RUNTIME_VERSION}" in result["detail"]


def test_qwen_incompatible_is_reported_as_outdated_not_corrupt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        diagnostics,
        "inspect_qwen_runtime",
        lambda _root, verify_worker: {
            "status": "incompatible",
            "version": "1.0.1",
            "worker": None,
        },
    )

    result = diagnostics._qwen_runtime_check(_runtime_paths(tmp_path))

    assert result["status"] == "fail"
    assert result["message"] == "Runtime Qwen está desatualizado para este Companion"
    assert "instalado v1.0.1" in result["detail"]
    assert f"mínimo v{diagnostics.MIN_COMPATIBLE_QWEN_RUNTIME_VERSION}" in result["detail"]


def test_maintenance_diagnostics_exports_only_known_bounded_json(tmp_path: Path):
    cache_root = tmp_path / "Cache"
    maintenance_root = cache_root / "maintenance"
    maintenance_root.mkdir(parents=True)
    (maintenance_root / "last-operation.json").write_text(
        json.dumps({"status": "failed", "error_code": "MSI_FAILED"}),
        encoding="utf-8",
    )
    (maintenance_root / "secret.txt").write_text("must-not-export", encoding="utf-8")
    (maintenance_root / "last-update.json").write_text("not-json", encoding="utf-8")
    paths = SimpleNamespace(cache_root=cache_root)

    result = diagnostics._maintenance_diagnostics(paths)

    assert result["last-operation.json"] == {
        "status": "failed",
        "error_code": "MSI_FAILED",
    }
    assert result["last-update.json"] == {"status": "unreadable"}
    assert "secret.txt" not in result
