from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tda_companion.desktop_session_bridge import SessionDesktopBridge


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


def test_handoff_reports_helper_exit_before_journal(tmp_path: Path):
    bridge = _bridge(tmp_path)
    bridge._maintenance_handoff_process = SimpleNamespace(poll=lambda: 7)

    with pytest.raises(RuntimeError, match="MAINTENANCE_EXITED_BEFORE_HANDOFF:7"):
        bridge._wait_maintenance_handoff("a" * 32, timeout=0.1)


def test_handoff_accepts_durable_operation_journal_even_if_helper_exits(tmp_path: Path):
    bridge = _bridge(tmp_path)
    operation_id = "b" * 32
    operation = tmp_path / "Cache" / "maintenance" / "operations" / f"{operation_id}.json"
    operation.parent.mkdir(parents=True)
    operation.write_text(
        json.dumps(
            {
                "operation_id": operation_id,
                "action": "update",
                "status": "running",
                "stage": "waiting_for_ui_exit",
            }
        ),
        encoding="utf-8",
    )
    bridge._maintenance_handoff_process = SimpleNamespace(poll=lambda: 9)

    bridge._wait_maintenance_handoff(operation_id, timeout=0.1)


def test_handoff_preserves_specific_failure_code(tmp_path: Path):
    bridge = _bridge(tmp_path)
    operation_id = "c" * 32
    operation = tmp_path / "Cache" / "maintenance" / "operations" / f"{operation_id}.json"
    operation.parent.mkdir(parents=True)
    operation.write_text(
        json.dumps(
            {
                "operation_id": operation_id,
                "action": "update",
                "status": "failed",
                "stage": "failed",
                "error_code": "UPDATE_HASH_MISMATCH",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="MAINTENANCE_HANDOFF_FAILED:UPDATE_HASH_MISMATCH"):
        bridge._wait_maintenance_handoff(operation_id, timeout=0.1)
