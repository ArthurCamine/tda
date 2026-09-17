from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import tda_companion.single_active_version as sav
from tda_companion.paths import CompanionPaths
from tda_companion.single_active_version import (
    InstalledCompanionProcess,
    SingleActiveVersionError,
    installed_image_identity,
    reconcile_packaged_installation,
    scan_installed_companion_processes,
)


def _paths(tmp_path: Path) -> CompanionPaths:
    return CompanionPaths.from_root(tmp_path / "TDA")


def _installed_executable(paths: CompanionPaths, version: str) -> Path:
    executable = paths.companion_root / "versions" / version / "TDACompanion.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"companion")
    return executable


def _write_guard(paths: CompanionPaths, action: str, target_version: str | None) -> Path:
    path = paths.cache_root / "maintenance" / "installation-guard.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "tda_installation_guard_v1",
                "action": action,
                "target_version": target_version,
                "created_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_missing_old_executable_is_still_recognized_as_installed_process(tmp_path: Path):
    paths = _paths(tmp_path)
    missing = paths.companion_root / "versions" / "0.3.4" / "TDACompanion.exe"
    process = SimpleNamespace(
        pid=9320,
        info={"pid": 9320, "name": "TDACompanion.exe", "exe": str(missing)},
    )

    observed = scan_installed_companion_processes(paths, process_iter=lambda: [process])

    assert observed == [
        InstalledCompanionProcess(pid=9320, image_path=missing, version="0.3.4")
    ]
    assert missing.exists() is False


def test_process_scan_uses_win32_image_fallback_when_psutil_cannot_resolve_exe(tmp_path: Path):
    paths = _paths(tmp_path)
    missing = paths.companion_root / "versions" / "0.3.4" / "TDACompanion.exe"

    class Process:
        pid = 9320
        info = {"pid": 9320, "name": "TDACompanion.exe", "exe": None}

        @staticmethod
        def exe():
            raise OSError("image unavailable through psutil")

    observed = scan_installed_companion_processes(
        paths,
        process_iter=lambda: [Process()],
        windows_image_lookup=lambda pid: missing if pid == 9320 else None,
    )

    assert observed == [
        InstalledCompanionProcess(pid=9320, image_path=missing, version="0.3.4")
    ]


def test_reconcile_kills_old_process_and_deletes_every_non_target_version(tmp_path: Path):
    paths = _paths(tmp_path)
    target = _installed_executable(paths, "0.3.8")
    _installed_executable(paths, "0.3.0")
    old_034 = _installed_executable(paths, "0.3.4")
    old_034.unlink()

    paths.state_root.mkdir(parents=True)
    paths.data_root.mkdir(parents=True)
    paths.models_root.mkdir(parents=True)
    paths.runtime_root.mkdir(parents=True)
    paths.cache_root.mkdir(parents=True)
    (paths.state_root / "settings.json").write_text("keep", encoding="utf-8")
    (paths.data_root / "jobs.sqlite3").write_text("keep", encoding="utf-8")
    (paths.models_root / "model.keep").write_text("keep", encoding="utf-8")
    (paths.runtime_root / "runtime.keep").write_text("keep", encoding="utf-8")
    maintenance = paths.cache_root / "maintenance"
    maintenance.mkdir(parents=True)
    (maintenance / "last-operation.json").write_text("keep", encoding="utf-8")

    for version in ("0.3.1", "0.3.8", "0.3.9"):
        update_dir = paths.cache_root / "updates" / version
        update_dir.mkdir(parents=True)
        (update_dir / "TDACompanion-x64.msi").write_bytes(b"msi")
    unknown_cache = paths.cache_root / "updates" / "future-channel"
    unknown_cache.mkdir(parents=True)
    (unknown_cache / "keep.txt").write_text("keep", encoding="utf-8")

    stale_marker = paths.companion_root / "current-version.txt.partial.1234"
    stale_marker.write_text("0.3.4", encoding="utf-8")

    alive = {9320}

    def scan():
        if 9320 not in alive:
            return []
        return [InstalledCompanionProcess(pid=9320, image_path=old_034, version="0.3.4")]

    terminated: list[int] = []

    def terminate(pid: int):
        terminated.append(pid)
        alive.discard(pid)

    result = reconcile_packaged_installation(
        paths,
        "0.3.8",
        target,
        current_pid=5000,
        scan=scan,
        terminate_pid=terminate,
        sleep=lambda _seconds: None,
    )

    assert result.applied is True
    assert result.terminated_pids == (9320,)
    assert set(result.removed_entries) == {"0.3.0", "0.3.4"}
    assert set(result.removed_update_cache_entries) == {"0.3.1", "0.3.8"}
    assert result.removed_metadata_entries == ("current-version.txt.partial.1234",)
    assert terminated == [9320]
    assert (paths.companion_root / "versions" / "0.3.8").is_dir()
    assert not (paths.companion_root / "versions" / "0.3.0").exists()
    assert not (paths.companion_root / "versions" / "0.3.4").exists()
    assert (paths.companion_root / "current-version.txt").read_text(encoding="utf-8").strip() == "0.3.8"
    assert not stale_marker.exists()

    assert not (paths.cache_root / "updates" / "0.3.1").exists()
    assert not (paths.cache_root / "updates" / "0.3.8").exists()
    assert (paths.cache_root / "updates" / "0.3.9" / "TDACompanion-x64.msi").is_file()
    assert (unknown_cache / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (maintenance / "last-operation.json").read_text(encoding="utf-8") == "keep"

    assert (paths.state_root / "settings.json").read_text(encoding="utf-8") == "keep"
    assert (paths.data_root / "jobs.sqlite3").read_text(encoding="utf-8") == "keep"
    assert (paths.models_root / "model.keep").read_text(encoding="utf-8") == "keep"
    assert (paths.runtime_root / "runtime.keep").read_text(encoding="utf-8") == "keep"


def test_older_binary_redirects_forward_instead_of_deleting_newer_install(tmp_path: Path):
    paths = _paths(tmp_path)
    old = _installed_executable(paths, "0.3.8")
    newer = _installed_executable(paths, "0.3.9")
    (paths.companion_root / "current-version.txt").write_text("0.3.9\n", encoding="utf-8")

    result = reconcile_packaged_installation(
        paths,
        "0.3.8",
        old,
        current_pid=5000,
        scan=lambda: [],
        terminate_pid=lambda _pid: pytest.fail("old binary must not terminate newer processes"),
        sleep=lambda _seconds: None,
    )

    assert result.applied is False
    assert result.redirect_executable == newer
    assert old.is_file()
    assert newer.is_file()
    assert (paths.companion_root / "current-version.txt").read_text(encoding="utf-8").strip() == "0.3.9"


def test_transaction_guard_allows_only_candidate_without_mutating_version_tree(tmp_path: Path):
    paths = _paths(tmp_path)
    old = _installed_executable(paths, "0.3.7")
    candidate = _installed_executable(paths, "0.3.8")
    _write_guard(paths, "major_upgrade", "0.3.8")

    candidate_result = reconcile_packaged_installation(paths, "0.3.8", candidate)
    assert candidate_result.applied is False
    assert old.is_file()
    assert candidate.is_file()

    with pytest.raises(SingleActiveVersionError, match="INSTALLATION_MAINTENANCE_ACTIVE"):
        reconcile_packaged_installation(paths, "0.3.7", old)


def test_stale_guard_is_self_cleaned_and_does_not_brick_startup(tmp_path: Path):
    paths = _paths(tmp_path)
    target = _installed_executable(paths, "0.3.8")
    guard = _write_guard(paths, "major_upgrade", "0.3.8")
    value = json.loads(guard.read_text(encoding="utf-8"))
    value["created_at"] = time.time() - 7200
    guard.write_text(json.dumps(value), encoding="utf-8")

    result = reconcile_packaged_installation(paths, "0.3.8", target, scan=lambda: [], sleep=lambda _s: None)

    assert result.applied is True
    assert not guard.exists()


def test_verified_termination_refuses_pid_identity_change(tmp_path: Path, monkeypatch):
    paths = _paths(tmp_path)
    observed = InstalledCompanionProcess(
        pid=9320,
        image_path=paths.companion_root / "versions" / "0.3.4" / "TDACompanion.exe",
        version="0.3.4",
    )
    foreign = tmp_path / "other" / "TDACompanion.exe"
    monkeypatch.setattr(sav, "_current_process_image", lambda _pid: foreign)
    monkeypatch.setattr(
        sav,
        "_terminate_pid",
        lambda _pid: pytest.fail("PID with changed identity must never be terminated"),
    )

    with pytest.raises(SingleActiveVersionError, match="STALE_TDA_PROCESS_IDENTITY_CHANGED"):
        sav._terminate_verified_installed_process(paths, observed)


def test_reconcile_refuses_to_continue_while_old_tda_process_survives(tmp_path: Path):
    paths = _paths(tmp_path)
    target = _installed_executable(paths, "0.3.8")
    old = paths.companion_root / "versions" / "0.3.4" / "TDACompanion.exe"
    process = InstalledCompanionProcess(pid=9320, image_path=old, version="0.3.4")

    with pytest.raises(SingleActiveVersionError, match="STALE_TDA_PROCESS_STILL_RUNNING"):
        reconcile_packaged_installation(
            paths,
            "0.3.8",
            target,
            current_pid=5000,
            scan=lambda: [process],
            terminate_pid=lambda _pid: None,
            sleep=lambda _seconds: None,
        )

    assert (paths.companion_root / "versions" / "0.3.4").parent.exists()


def test_reconcile_ignores_non_installed_development_execution(tmp_path: Path):
    paths = _paths(tmp_path)
    _installed_executable(paths, "0.3.8")
    old = _installed_executable(paths, "0.3.4")
    development_python = tmp_path / "python.exe"
    development_python.write_bytes(b"python")

    result = reconcile_packaged_installation(paths, "0.3.8", development_python)

    assert result.applied is False
    assert old.is_file()


def test_recovery_identity_never_trusts_same_named_binary_outside_versions_root(tmp_path: Path):
    paths = _paths(tmp_path)
    foreign = tmp_path / "attacker" / "TDACompanion.exe"
    foreign.parent.mkdir(parents=True)

    belongs, version = installed_image_identity(foreign, paths.companion_root / "versions")

    assert belongs is False
    assert version is None
