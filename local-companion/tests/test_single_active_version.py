from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_reconcile_kills_old_process_and_deletes_every_non_target_version(tmp_path: Path):
    paths = _paths(tmp_path)
    target = _installed_executable(paths, "0.3.8")
    old_030 = _installed_executable(paths, "0.3.0")
    old_034 = _installed_executable(paths, "0.3.4")
    old_034.unlink()  # Reproduce the real zombie: process alive, image gone from disk.

    paths.state_root.mkdir(parents=True)
    paths.data_root.mkdir(parents=True)
    paths.models_root.mkdir(parents=True)
    paths.runtime_root.mkdir(parents=True)
    (paths.state_root / "settings.json").write_text("keep", encoding="utf-8")
    (paths.data_root / "jobs.sqlite3").write_text("keep", encoding="utf-8")
    (paths.models_root / "model.keep").write_text("keep", encoding="utf-8")
    (paths.runtime_root / "runtime.keep").write_text("keep", encoding="utf-8")

    alive = {9320}

    def scan():
        if 9320 not in alive:
            return []
        return [
            InstalledCompanionProcess(
                pid=9320,
                image_path=old_034,
                version="0.3.4",
            )
        ]

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
    assert terminated == [9320]
    assert (paths.companion_root / "versions" / "0.3.8").is_dir()
    assert not (paths.companion_root / "versions" / "0.3.0").exists()
    assert not (paths.companion_root / "versions" / "0.3.4").exists()
    assert (paths.companion_root / "current-version.txt").read_text(encoding="utf-8").strip() == "0.3.8"

    assert (paths.state_root / "settings.json").read_text(encoding="utf-8") == "keep"
    assert (paths.data_root / "jobs.sqlite3").read_text(encoding="utf-8") == "keep"
    assert (paths.models_root / "model.keep").read_text(encoding="utf-8") == "keep"
    assert (paths.runtime_root / "runtime.keep").read_text(encoding="utf-8") == "keep"


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

    # Cleanup must not run while a process from the old version is still alive.
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
