from __future__ import annotations

import json
from pathlib import Path

import pytest

from tda_companion.maintenance_recovery import recover_interrupted_maintenance
from tda_companion.paths import CompanionPaths


def _paths(tmp_path: Path) -> CompanionPaths:
    return CompanionPaths.from_root(tmp_path / "TDA")


def _installed(paths: CompanionPaths, version: str) -> Path:
    root = paths.companion_root / "versions" / version
    executable = root / "TDACompanion.exe"
    maintenance = root / "TDACompanionMaintenance.exe"
    base_library = root / "_internal" / "base_library.zip"
    base_library.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"app")
    maintenance.write_bytes(b"maintenance")
    base_library.write_bytes(b"base-library")
    (paths.companion_root / "current-version.txt").write_text(version + "\n", encoding="utf-8")
    return executable


def _journal(paths: CompanionPaths, value: dict[str, object]) -> Path:
    root = paths.cache_root / "maintenance"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "last-operation.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_stale_running_update_is_completed_when_target_installation_survived(tmp_path: Path):
    paths = _paths(tmp_path)
    executable = _installed(paths, "0.3.8")
    operation_id = "a" * 32
    last = _journal(
        paths,
        {
            "schema_version": 1,
            "operation_id": operation_id,
            "action": "update",
            "status": "running",
            "stage": "restarting_ui",
            "target_version": "0.3.8",
            "updated_at": 100.0,
            "error_code": None,
            "failure_stage": None,
        },
    )

    recovered = recover_interrupted_maintenance(
        paths,
        "0.3.8",
        executable,
        now=500.0,
    )

    assert recovered is not None
    assert recovered["status"] == "completed"
    assert recovered["stage"] == "recovered_after_interruption"
    assert recovered["error_code"] is None
    assert json.loads(last.read_text(encoding="utf-8"))["status"] == "completed"
    operation = paths.cache_root / "maintenance" / "operations" / f"{operation_id}.json"
    assert json.loads(operation.read_text(encoding="utf-8"))["recovery"] == "target_installation_survived"


def test_partial_target_is_never_recovered_as_success_even_after_post_msi_stage(tmp_path: Path):
    paths = _paths(tmp_path)
    executable = _installed(paths, "0.3.8")
    (paths.companion_root / "versions" / "0.3.8" / "TDACompanionMaintenance.exe").unlink()
    _journal(
        paths,
        {
            "schema_version": 1,
            "operation_id": "f" * 32,
            "action": "update",
            "status": "running",
            "stage": "restarting_ui",
            "target_version": "0.3.8",
            "updated_at": 100.0,
        },
    )

    recovered = recover_interrupted_maintenance(paths, "0.3.8", executable, now=500.0)

    assert recovered is not None
    assert recovered["status"] == "failed"
    assert recovered["error_code"] == "UPDATE_INTERRUPTED_ROLLED_BACK"
    assert recovered["recovery"] == "running_version_survived_or_target_incomplete"


@pytest.mark.parametrize(
    "stage",
    ["accepted", "waiting_for_ui_exit", "verifying_asset", "running_msi"],
)
def test_same_version_target_never_proves_early_interrupted_update_succeeded(
    tmp_path: Path,
    stage: str,
):
    paths = _paths(tmp_path)
    executable = _installed(paths, "0.3.8")
    _journal(
        paths,
        {
            "schema_version": 1,
            "operation_id": "e" * 32,
            "action": "update",
            "status": "running",
            "stage": stage,
            "target_version": "0.3.8",
            "updated_at": 100.0,
        },
    )

    recovered = recover_interrupted_maintenance(paths, "0.3.8", executable, now=500.0)

    assert recovered is not None
    assert recovered["status"] == "failed"
    assert recovered["failure_stage"] == stage
    assert recovered["error_code"] == "UPDATE_INTERRUPTED_UNVERIFIED"
    assert recovered["recovery"] == "target_present_but_completion_unproven"


def test_stale_update_is_marked_rolled_back_when_previous_version_survived(tmp_path: Path):
    paths = _paths(tmp_path)
    executable = _installed(paths, "0.3.7")
    _journal(
        paths,
        {
            "schema_version": 1,
            "operation_id": "b" * 32,
            "action": "update",
            "status": "running",
            "stage": "running_msi",
            "target_version": "0.3.8",
            "updated_at": 100.0,
        },
    )

    recovered = recover_interrupted_maintenance(paths, "0.3.7", executable, now=500.0)

    assert recovered is not None
    assert recovered["status"] == "failed"
    assert recovered["error_code"] == "UPDATE_INTERRUPTED_ROLLED_BACK"
    assert recovered["failure_stage"] == "running_msi"


def test_fresh_running_journal_is_never_second_guessed(tmp_path: Path):
    paths = _paths(tmp_path)
    executable = _installed(paths, "0.3.8")
    last = _journal(
        paths,
        {
            "schema_version": 1,
            "operation_id": "c" * 32,
            "action": "update",
            "status": "running",
            "stage": "verifying_agent",
            "target_version": "0.3.8",
            "updated_at": 450.0,
        },
    )
    before = last.read_text(encoding="utf-8")

    assert recover_interrupted_maintenance(paths, "0.3.8", executable, now=500.0) is None
    assert last.read_text(encoding="utf-8") == before


def test_stale_uninstall_journal_closes_failed_if_app_can_still_start(tmp_path: Path):
    paths = _paths(tmp_path)
    executable = _installed(paths, "0.3.8")
    _journal(
        paths,
        {
            "schema_version": 1,
            "operation_id": "d" * 32,
            "action": "uninstall",
            "status": "running",
            "stage": "running_msi",
            "updated_at": 100.0,
        },
    )

    recovered = recover_interrupted_maintenance(paths, "0.3.8", executable, now=500.0)

    assert recovered is not None
    assert recovered["status"] == "failed"
    assert recovered["error_code"] == "UNINSTALL_INTERRUPTED"
