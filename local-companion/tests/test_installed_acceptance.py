from __future__ import annotations

import json
from pathlib import Path

from tda_companion import VERSION
from tda_companion.installed_acceptance import summarize_diagnostics, write_receipt


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
    assert value["pass"] is True
    assert not destination.with_name(destination.name + ".partial").exists()
