from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tda_companion import VERSION
from tda_companion.installed_acceptance import (
    REQUIRED_OBSERVATIONS,
    finalize_installed_acceptance,
    summarize_diagnostics,
    write_receipt,
)


def test_diagnostic_summary_is_capability_only():
    value = summarize_diagnostics(
        {
            "overall": "degraded",
            "capabilities": {
                "core": {"state": "ready", "severity": "info", "detail": "ignored"},
                "network": {"state": "degraded", "severity": "degraded"},
            },
        }
    )
    assert value == {
        "overall": "degraded",
        "capabilities": {
            "core": {"state": "ready", "severity": "info"},
            "network": {"state": "degraded", "severity": "degraded"},
        },
    }


def test_diagnostic_summary_accepts_real_run_diagnostics_list_shape():
    value = summarize_diagnostics(
        {
            "overall": "pass",
            "capabilities": [
                {"id": "core", "status": "ready", "severity": "info", "message": "Pronto"},
                {"id": "network", "status": "ready", "severity": "info", "message": "Pronto"},
                {"id": "maintenance", "status": "ready", "severity": "info", "message": "Pronto"},
                {"id": "whisper", "status": "degraded", "severity": "degraded", "message": "Modelo ausente"},
                {"id": "qwen", "status": "blocked", "severity": "blocker", "message": "Gate pendente"},
            ],
        }
    )
    assert value == {
        "overall": "pass",
        "capabilities": {
            "core": {"state": "ready", "severity": "info"},
            "network": {"state": "ready", "severity": "info"},
            "maintenance": {"state": "ready", "severity": "info"},
            "whisper": {"state": "degraded", "severity": "degraded"},
            "qwen": {"state": "blocked", "severity": "blocker"},
        },
    }


def test_receipt_is_written_atomically(tmp_path: Path):
    destination = tmp_path / "receipt.json"
    value = write_receipt(
        destination,
        passed=True,
        stage="completed",
        artifact={"version": VERSION, "executable_sha256": "a" * 64},
        checks={"agent": {"pass": True, "state": "ready"}},
    )
    assert json.loads(destination.read_text(encoding="utf-8")) == value
    assert value["schema"] == "tda_installed_acceptance_v2"
    assert value["pass"] is True
    assert value["contains_token"] is False
    assert value["contains_paths"] is False
    assert value["contains_transcript"] is False
    assert not destination.with_name(destination.name + ".partial").exists()


def test_incomplete_observations_fail_before_artifact_or_diagnostics(tmp_path: Path):
    destination = tmp_path / "receipt.json"
    missing = sorted(REQUIRED_OBSERVATIONS - {"port_conflict"})

    value = finalize_installed_acceptance(
        executable=tmp_path / "not-used",
        paths=SimpleNamespace(),
        port=8765,
        candidate_msi=tmp_path / "not-used.msi",
        payload_manifest=tmp_path / "not-used.json",
        source_sha="0" * 40,
        craig_zip=tmp_path / "not-used.zip",
        observations=missing,
        destination=destination,
    )

    assert value["pass"] is False
    assert value["stage"] == "manual_observations"
    assert value["error_code"] == "ACCEPTANCE_OBSERVATIONS_INCOMPLETE"
    assert value["checks"]["observations"]["port_conflict"] is False
