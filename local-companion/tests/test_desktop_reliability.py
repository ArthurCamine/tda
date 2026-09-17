from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import tda_companion.desktop_session_bridge as desktop_session_bridge

from tda_companion.agent_connection import AgentConnectionError
from tda_companion.desktop import DesktopBridge
from tda_companion.desktop_session_bridge import SessionDesktopBridge
from tda_companion.large_download import LargeDownloadError
from tda_companion.network import NetworkError
from tda_companion.system_log import SystemLog


def _bridge(tmp_path: Path) -> SessionDesktopBridge:
    paths = SimpleNamespace(
        root=tmp_path,
        companion_root=tmp_path / "Companion",
        state_root=tmp_path / "State",
        data_root=tmp_path / "Data",
        logs_root=tmp_path / "Logs",
        cache_root=tmp_path / "Cache",
        models_root=tmp_path / "Models",
        runtime_root=tmp_path / "Runtime",
    )
    for path in (
        paths.state_root,
        paths.data_root,
        paths.logs_root,
        paths.cache_root,
        paths.models_root,
        paths.runtime_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(
        snapshot=lambda: {
            "start_with_windows": False,
            "show_tray": False,
            "check_updates": False,
            "theme": "system",
            "close_behavior": "hide",
        },
        update=lambda value: value,
    )
    return SessionDesktopBridge(
        token="t" * 43,
        port=8765,
        paths=paths,
        settings=settings,
        executable=tmp_path / "TDACompanion.exe",
        start_agent=lambda: None,
    )


def _offline(connection, code: str = "AGENT_CONNECTION_REFUSED") -> None:
    connection._state = "unavailable"
    connection._last_error = code


def test_snapshot_remains_renderable_when_agent_is_unavailable(monkeypatch, tmp_path: Path):
    bridge = _bridge(tmp_path)
    _offline(bridge.client)
    monkeypatch.setattr(
        bridge.client,
        "get",
        lambda _path: (_ for _ in ()).throw(AgentConnectionError("AGENT_CONNECTION_REFUSED")),
    )

    value = bridge.snapshot()

    assert value["version"]
    assert value["agent"]["lifecycle"] == "unavailable"
    assert value["agent"]["error"] == "AGENT_CONNECTION_REFUSED"
    assert value["connection"]["state"] == "unavailable"
    assert value["settings"]["close_behavior"] == "hide"
    assert value["jobs"] == []


def test_profile_discovery_failure_does_not_invalidate_selected_craig(monkeypatch, tmp_path: Path):
    bridge = _bridge(tmp_path)
    source_id = "craig-" + "a" * 64
    bridge._selected_sources.add(source_id)
    _offline(bridge.client)
    monkeypatch.setattr(
        bridge.client,
        "get",
        lambda _path: (_ for _ in ()).throw(AgentConnectionError("AGENT_CONNECTION_REFUSED")),
    )

    result = bridge.transcription_profiles()

    assert source_id in bridge._selected_sources
    assert result["profiles"] == []
    assert result["unavailable"] is True
    assert result["error"] == "AGENT_CONNECTION_REFUSED"


def test_background_logs_use_local_fallback_when_agent_is_unavailable(monkeypatch, tmp_path: Path):
    bridge = _bridge(tmp_path)
    _offline(bridge.client)
    SystemLog(bridge.paths.logs_root).write(
        "warning",
        "bootstrap",
        "AGENT_RECOVERY_TEST",
        "local log remains readable",
    )
    monkeypatch.setattr(
        bridge.client,
        "get",
        lambda _path: (_ for _ in ()).throw(AgentConnectionError("AGENT_CONNECTION_REFUSED")),
    )

    result = bridge.logs(limit=50)

    assert result["local_fallback"] is True
    assert result["error"] == "AGENT_CONNECTION_REFUSED"
    assert result["connection"]["state"] == "unavailable"
    assert len(result["logs"]) == 1
    assert result["logs"][0]["code"] == "AGENT_RECOVERY_TEST"
    assert result["logs"][0]["message"] == "local log remains readable"


def test_installed_bridge_correlates_maintenance_operation_id(monkeypatch, tmp_path: Path):
    bridge = _bridge(tmp_path)
    seen: dict[str, list[str]] = {}
    handoffs: list[str] = []

    def fake_launch(self, arguments):  # noqa: ANN001
        seen["arguments"] = list(arguments)
        return True

    def fake_install(self):  # noqa: ANN001
        self._launch_maintenance(["--install-update", "--version", "0.3.3"])
        return {"accepted": True, "available": True, "version": "0.3.3"}

    monkeypatch.setattr(DesktopBridge, "_launch_maintenance", fake_launch)
    monkeypatch.setattr(DesktopBridge, "install_update", fake_install)
    monkeypatch.setattr(
        SessionDesktopBridge,
        "_wait_maintenance_handoff",
        lambda self, operation_id, timeout=3.0: handoffs.append(operation_id),
    )

    result = bridge.install_update()

    operation_id = result["operation_id"]
    assert isinstance(operation_id, str) and len(operation_id) == 32
    assert seen["arguments"][-2:] == ["--operation-id", operation_id]
    assert "--cleanup-self" in seen["arguments"]
    assert handoffs == [operation_id]


def test_staged_maintenance_helper_lives_outside_tda_root(monkeypatch, tmp_path: Path):
    bridge = _bridge(tmp_path)
    operation_id = "1" * 32
    bridge._last_maintenance_operation_id = operation_id
    source = tmp_path / "TDACompanionMaintenance.exe"
    source.write_bytes(b"helper")
    temp_root = tmp_path.parent / f"{tmp_path.name}-system-temp"
    shutil.rmtree(temp_root, ignore_errors=True)
    monkeypatch.setattr(
        desktop_session_bridge.tempfile,
        "gettempdir",
        lambda: str(temp_root),
    )
    try:
        helper = bridge._maintenance_helper()
        assert helper.read_bytes() == b"helper"
        assert tmp_path not in helper.parents
        assert helper.parent.name == operation_id
        assert helper.parent.parent.name == "TDACompanionMaintenance"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_failed_handoff_blocks_ui_close_contract(tmp_path: Path):
    bridge = _bridge(tmp_path)
    operation_id = "f" * 32
    operation_root = tmp_path / "Cache" / "maintenance" / "operations"
    operation_root.mkdir(parents=True)
    (operation_root / f"{operation_id}.json").write_text(
        json.dumps(
            {
                "operation_id": operation_id,
                "action": "update",
                "status": "failed",
                "stage": "failed",
                "error_code": "MAINTENANCE_START_FAILED",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="MAINTENANCE_HANDOFF_FAILED"):
        bridge._wait_maintenance_handoff(operation_id, timeout=0.1)


def test_snapshot_exposes_only_sanitized_maintenance_fields(monkeypatch, tmp_path: Path):
    bridge = _bridge(tmp_path)
    maintenance_root = tmp_path / "Cache" / "maintenance"
    maintenance_root.mkdir(parents=True)
    (maintenance_root / "last-operation.json").write_text(
        json.dumps(
            {
                "operation_id": "e" * 32,
                "action": "update",
                "status": "failed",
                "stage": "failed",
                "failure_stage": "running_msi",
                "error_code": "MSI_FAILED",
                "msi_exit_code": 1603,
                "target_version": "0.3.3",
                "updated_at": 123.0,
                "private_path": r"C:\Users\secret\candidate.msi",
                "exception": "private stack trace",
            }
        ),
        encoding="utf-8",
    )
    _offline(bridge.client)
    monkeypatch.setattr(
        bridge.client,
        "get",
        lambda _path: (_ for _ in ()).throw(AgentConnectionError("AGENT_CONNECTION_REFUSED")),
    )

    value = bridge.snapshot()["maintenance"]

    assert value == {
        "operation_id": "e" * 32,
        "action": "update",
        "status": "failed",
        "stage": "failed",
        "failure_stage": "running_msi",
        "error_code": "MSI_FAILED",
        "msi_exit_code": 1603,
        "target_version": "0.3.3",
        "updated_at": 123.0,
    }


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("OFFLINE", "sem acesso à Internet"),
        ("DNS_FAILED", "resolver o endereço do TDA"),
        ("PROXY_FAILED", "proxy configurado"),
        ("CONNECT_TIMEOUT", "demorou demais"),
        ("TLS_FAILED", "conexão segura"),
        ("HTTP_ERROR", "respondeu com erro"),
        ("MANIFEST_INVALID", "dados inválidos"),
        ("HASH_MISMATCH", "verificação de integridade"),
        ("DOWNLOAD_CONTINUES_IN_BACKGROUND", "continua em segundo plano"),
        ("BITS_TRANSFER_FAILED", "download em segundo plano do Windows"),
        ("UPDATE_SIZE_MISMATCH", "tamanho publicado"),
        ("QWEN_RUNTIME_PART_SIZE_EXCEEDED", "tamanho publicado"),
        ("DOWNLOAD_OUTPUT_MISSING", "arquivo esperado"),
    ],
)
def test_network_failures_have_user_message_and_stable_code(tmp_path: Path, code: str, message: str):
    bridge = _bridge(tmp_path)
    error = bridge._friendly_network_error(NetworkError(code))
    text = str(error)
    assert message in text
    assert text.endswith(f"[{code}]")


def test_large_download_errors_share_the_installed_network_boundary():
    error = LargeDownloadError("BITS_TRANSFER_FAILED")
    assert isinstance(error, NetworkError)
    assert error.code == "BITS_TRANSFER_FAILED"


def test_update_check_translates_network_failure_at_installed_ui_boundary(monkeypatch, tmp_path: Path):
    bridge = _bridge(tmp_path)
    monkeypatch.setattr(
        DesktopBridge,
        "check_update",
        lambda self: (_ for _ in ()).throw(NetworkError("DNS_FAILED")),
    )

    with pytest.raises(RuntimeError) as exc:
        bridge.check_update()

    assert "resolver o endereço do TDA" in str(exc.value)
    assert "[DNS_FAILED]" in str(exc.value)


def test_install_update_translates_background_download_state(monkeypatch, tmp_path: Path):
    bridge = _bridge(tmp_path)
    monkeypatch.setattr(
        DesktopBridge,
        "install_update",
        lambda self: (_ for _ in ()).throw(
            LargeDownloadError("DOWNLOAD_CONTINUES_IN_BACKGROUND")
        ),
    )

    with pytest.raises(RuntimeError) as exc:
        bridge.install_update()

    text = str(exc.value)
    assert "continua em segundo plano" in text
    assert "retomará o mesmo download" in text
    assert text.endswith("[DOWNLOAD_CONTINUES_IN_BACKGROUND]")
