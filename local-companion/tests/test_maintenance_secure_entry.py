from __future__ import annotations

import importlib.util
import json
import sys
import types
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_secure_module():
    if "winreg" not in sys.modules:
        stub = types.ModuleType("winreg")
        stub.HKEY_CURRENT_USER = object()
        stub.KEY_SET_VALUE = 0
        stub.KEY_READ = 0
        sys.modules["winreg"] = stub
    packaging = Path(__file__).parents[1] / "packaging"
    if str(packaging) not in sys.path:
        sys.path.insert(0, str(packaging))
    for name in ("maintenance_entry", "tda_companion_maintenance_secure_test"):
        sys.modules.pop(name, None)
    path = packaging / "maintenance_secure_entry.py"
    spec = importlib.util.spec_from_file_location("tda_companion_maintenance_secure_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _complete_install(root: Path, version: str = "0.3.8") -> Path:
    version_root = root / "Companion" / "versions" / version
    executable = version_root / "TDACompanion.exe"
    maintenance = version_root / "TDACompanionMaintenance.exe"
    base_library = version_root / "_internal" / "base_library.zip"
    base_library.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"app")
    maintenance.write_bytes(b"maintenance")
    base_library.write_bytes(b"base-library")
    return executable


def test_secure_uninstall_never_reads_token_or_mutates_msi_owned_startup(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    legacy = secure.legacy
    terminated: list[int] = []
    alive = {222}

    monkeypatch.setattr(
        legacy,
        "_remove_startup_value",
        lambda: pytest.fail("secure maintenance must leave MSI-owned Startup state to MSI"),
    )
    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: (sorted(alive), []))

    def terminate(_root: Path, pid: int):
        terminated.append(pid)
        alive.discard(pid)

    monkeypatch.setattr(secure, "_terminate_verified_pid", terminate)
    monkeypatch.setattr(secure.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        legacy,
        "_token",
        lambda _root: (_ for _ in ()).throw(AssertionError("maintenance must not read pairing token")),
    )
    monkeypatch.setattr(
        legacy,
        "_agent_post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("maintenance must not send authenticated loopback requests")
        ),
    )

    secure.prepare_uninstall(tmp_path, 8765)

    assert terminated == [222]
    assert alive == set()


def test_prepare_install_guards_stops_old_processes_and_proves_port_free(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    alive = {222}
    terminated: list[int] = []
    port_checks: list[int] = []

    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: (sorted(alive), []))

    def terminate(_root: Path, pid: int):
        terminated.append(pid)
        alive.discard(pid)

    monkeypatch.setattr(secure, "_terminate_verified_pid", terminate)
    monkeypatch.setattr(secure.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(secure, "_wait_port_free", lambda port: port_checks.append(port))

    secure.prepare_major_upgrade(tmp_path, 8765, "0.3.8")

    assert terminated == [222]
    assert alive == set()
    assert port_checks == [8765]
    guard = json.loads((tmp_path / "Cache" / "maintenance" / "installation-guard.json").read_text(encoding="utf-8"))
    assert guard["action"] == "major_upgrade"
    assert guard["target_version"] == "0.3.8"


def test_prepare_holds_reconcile_lock_across_guard_and_process_shutdown(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    observed: list[tuple[str, bool]] = []
    lock_held = False

    @contextmanager
    def lock():
        nonlocal lock_held
        lock_held = True
        observed.append(("lock_enter", lock_held))
        try:
            yield
        finally:
            observed.append(("lock_exit", lock_held))
            lock_held = False

    def stop(root: Path, **_kwargs):
        observed.append(("stop", lock_held))
        assert (root / "Cache" / "maintenance" / "installation-guard.json").is_file()

    monkeypatch.setattr(secure, "_installation_reconcile_lock", lock)
    monkeypatch.setattr(secure, "_stop_installed_processes", stop)

    secure.prepare_major_upgrade(tmp_path, 8765, "0.3.8")

    assert observed == [("lock_enter", True), ("stop", True), ("lock_exit", True)]


def test_direct_uninstall_guard_exists_before_process_shutdown(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    observed: list[bool] = []

    def stop(root: Path, **_kwargs):
        observed.append((root / "Cache" / "maintenance" / "installation-guard.json").is_file())

    monkeypatch.setattr(secure, "_stop_installed_processes", stop)

    secure.prepare_explicit_uninstall(tmp_path)

    assert observed == [True]
    guard = json.loads((tmp_path / "Cache" / "maintenance" / "installation-guard.json").read_text(encoding="utf-8"))
    assert guard["action"] == "uninstall"
    assert guard["target_version"] is None


def test_prepare_actions_clear_guard_when_quiescence_fails(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    monkeypatch.setattr(
        secure,
        "_stop_installed_processes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(secure.legacy.MaintenanceError("STOP_FAILED")),
    )

    with pytest.raises(secure.legacy.MaintenanceError, match="STOP_FAILED"):
        secure.prepare_major_upgrade(tmp_path, 8765, "0.3.8")
    assert not (tmp_path / "Cache" / "maintenance" / "installation-guard.json").exists()

    with pytest.raises(secure.legacy.MaintenanceError, match="STOP_FAILED"):
        secure.prepare_explicit_uninstall(tmp_path)
    assert not (tmp_path / "Cache" / "maintenance" / "installation-guard.json").exists()


def test_explicit_uninstall_final_check_does_not_block_on_unrelated_listener(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: ([], []))
    monkeypatch.setattr(
        secure,
        "_wait_port_free",
        lambda _port: pytest.fail("explicit uninstall must not depend on unrelated Agent port ownership"),
    )

    secure.prepare_uninstall(tmp_path, 8765)


def test_secure_msi_action_cli_owns_prepare_uninstall_verify_commit_and_rollback(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    observed: list[tuple[str, Path, object]] = []
    monkeypatch.setattr(
        secure,
        "prepare_major_upgrade",
        lambda root, port=8765, target_version=None: observed.append(("prepare", root, (port, target_version))),
    )
    monkeypatch.setattr(
        secure,
        "prepare_explicit_uninstall",
        lambda root: observed.append(("uninstall", root, None)),
    )
    monkeypatch.setattr(
        secure,
        "verify_installed_target",
        lambda root, version, port=8765: observed.append(("verify", root, (port, version))),
    )
    monkeypatch.setattr(secure, "finish_major_upgrade", lambda root: observed.append(("finish", root, None)))
    monkeypatch.setattr(
        secure,
        "rollback_major_upgrade",
        lambda root, port=8765: observed.append(("rollback", root, port)),
    )
    monkeypatch.setattr(
        secure.legacy,
        "main",
        lambda _argv: pytest.fail("legacy parser must not receive secure MSI actions"),
    )

    assert secure.main(["--prepare-major-upgrade", "--root", str(tmp_path), "--port", "9876", "--target-version", "0.3.8"]) == 0
    assert secure.main(["--prepare-explicit-uninstall", "--root", str(tmp_path)]) == 0
    assert secure.main(["--verify-installed-target", "--root", str(tmp_path), "--target-version", "0.3.8"]) == 0
    assert secure.main(["--finish-major-upgrade", "--root", str(tmp_path)]) == 0
    assert secure.main(["--rollback-major-upgrade", "--root", str(tmp_path)]) == 0
    assert observed == [
        ("prepare", tmp_path.resolve(), (9876, "0.3.8")),
        ("uninstall", tmp_path.resolve(), None),
        ("verify", tmp_path.resolve(), (8765, "0.3.8")),
        ("finish", tmp_path.resolve(), None),
        ("rollback", tmp_path.resolve(), 8765),
    ]


def test_rollback_clears_guard_and_restarts_restored_agent(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    guard = tmp_path / "Cache" / "maintenance" / "installation-guard.json"
    guard.parent.mkdir(parents=True)
    guard.write_text("{}", encoding="utf-8")
    observed: list[object] = []

    monkeypatch.setattr(secure, "_installation_reconcile_lock", lambda: nullcontext())
    monkeypatch.setattr(secure, "_stop_installed_processes", lambda root: observed.append(("stop", root)))
    monkeypatch.setattr(
        secure,
        "_restart_surviving_agent",
        lambda root, port: observed.append(("restart", root, port)),
    )

    secure.rollback_major_upgrade(tmp_path, 9876)

    assert not guard.exists()
    assert observed == [("stop", tmp_path), ("restart", tmp_path, 9876)]


def test_secure_maintenance_fails_closed_when_old_process_survives(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: ([222], []))
    monkeypatch.setattr(secure, "_terminate_verified_pid", lambda _root, _pid: None)
    monkeypatch.setattr(secure.time, "sleep", lambda _seconds: None)

    with pytest.raises(secure.legacy.MaintenanceError, match="TDA_PROCESS_STILL_RUNNING"):
        secure.prepare_uninstall(tmp_path, 8765)


def test_secure_maintenance_fails_closed_when_process_identity_is_unreadable(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: ([], [9320]))
    monkeypatch.setattr(
        secure,
        "_terminate_verified_pid",
        lambda *_args: pytest.fail("unverified same-name process must never be killed blindly"),
    )

    with pytest.raises(secure.legacy.MaintenanceError, match="TDA_PROCESS_IDENTITY_UNVERIFIED"):
        secure.prepare_major_upgrade(tmp_path, 8765, "0.3.8")


def test_verified_termination_rechecks_process_image_before_kill(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    outside = tmp_path.parent / "other" / "TDACompanion.exe"
    monkeypatch.setattr(secure.legacy, "_process_image", lambda _pid: outside)
    monkeypatch.setattr(
        secure.legacy,
        "_terminate_pid",
        lambda _pid: pytest.fail("changed PID identity must not be terminated"),
    )

    with pytest.raises(secure.legacy.MaintenanceError, match="TDA_PROCESS_IDENTITY_CHANGED"):
        secure._terminate_verified_pid(tmp_path, 9320)


def test_verified_termination_rejects_nested_or_non_semver_install_path(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    nested = tmp_path / "Companion" / "versions" / "0.3.4" / "nested" / "TDACompanion.exe"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"app")
    monkeypatch.setattr(secure.legacy, "_process_image", lambda _pid: nested)
    monkeypatch.setattr(
        secure.legacy,
        "_terminate_pid",
        lambda _pid: pytest.fail("non-canonical install path must never be killed"),
    )

    with pytest.raises(secure.legacy.MaintenanceError, match="TDA_PROCESS_IDENTITY_CHANGED"):
        secure._terminate_verified_pid(tmp_path, 9320)


def test_prepare_install_fails_closed_when_agent_port_never_frees(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: ([], []))
    monkeypatch.setattr(secure, "_port_is_free", lambda _port: False)
    monkeypatch.setattr(secure.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 10.0])
    monkeypatch.setattr(secure.time, "monotonic", lambda: next(ticks, 10.0))

    with pytest.raises(secure.legacy.MaintenanceError, match="AGENT_PORT_STILL_OCCUPIED"):
        secure.prepare_major_upgrade(tmp_path, 8765, "0.3.8")

    assert not (tmp_path / "Cache" / "maintenance" / "installation-guard.json").exists()


def test_listener_owner_requires_exact_single_loopback_pid(monkeypatch):
    secure = _load_secure_module()
    listener = lambda pid, host="127.0.0.1": SimpleNamespace(  # noqa: E731
        status="LISTEN",
        laddr=(host, 8765),
        pid=pid,
    )

    monkeypatch.setattr(secure.psutil, "net_connections", lambda kind: [listener(9320)])
    assert secure._listener_owned_by(8765, 9320) is True

    monkeypatch.setattr(secure.psutil, "net_connections", lambda kind: [listener(9320), listener(2222)])
    assert secure._listener_owned_by(8765, 9320) is False

    monkeypatch.setattr(secure.psutil, "net_connections", lambda kind: [listener(9320, "0.0.0.0")])
    assert secure._listener_owned_by(8765, 9320) is False


def test_target_health_requires_real_listener_owner_and_exact_image(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    executable = tmp_path / "Companion" / "versions" / "0.3.8" / "TDACompanion.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"app")
    monkeypatch.setattr(
        secure,
        "_target_health",
        lambda _port: {
            "product_id": "tda-companion",
            "api_version": "1",
            "service_version": "0.3.8",
            "pid": 9320,
            "port": 8765,
        },
    )
    monkeypatch.setattr(secure.legacy, "_process_image", lambda _pid: executable)
    monkeypatch.setattr(secure, "_listener_owned_by", lambda _port, _pid: False)
    assert secure._health_matches_target(executable, "0.3.8", 8765) is False

    monkeypatch.setattr(secure, "_listener_owned_by", lambda _port, _pid: True)
    assert secure._health_matches_target(executable, "0.3.8", 8765) is True


def test_verify_installed_target_starts_candidate_and_requires_exact_health(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    executable = _complete_install(tmp_path)
    observed: list[tuple[Path, str, int]] = []

    monkeypatch.setattr(secure, "_health_matches_target", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(secure, "_port_is_free", lambda _port: True)
    monkeypatch.setattr(
        secure,
        "_spawn_target_agent",
        lambda exe, version, port: observed.append((exe, version, port)),
    )

    secure.verify_installed_target(tmp_path, "0.3.8", 8765)

    assert observed == [(executable, "0.3.8", 8765)]


def test_verify_installed_target_rejects_partial_version_before_agent_start(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    executable = tmp_path / "Companion" / "versions" / "0.3.8" / "TDACompanion.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"app")
    monkeypatch.setattr(
        secure,
        "_spawn_target_agent",
        lambda *_args, **_kwargs: pytest.fail("partial target must not start"),
    )

    with pytest.raises(secure.legacy.MaintenanceError, match="UPDATED_INSTALLATION_INCOMPLETE"):
        secure.verify_installed_target(tmp_path, "0.3.8", 8765)


def test_spawn_candidate_retries_without_breakaway_when_installer_job_rejects_it(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    executable = tmp_path / "TDACompanion.exe"
    executable.write_bytes(b"app")
    calls: list[int] = []
    process = SimpleNamespace(pid=9320, poll=lambda: None)
    monkeypatch.setattr(secure.legacy.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000, raising=False)

    def popen(*_args, creationflags=0, **_kwargs):
        calls.append(creationflags)
        if len(calls) == 1:
            raise OSError("job refuses breakaway")
        return process

    monkeypatch.setattr(secure.legacy.subprocess, "Popen", popen)
    monkeypatch.setattr(secure, "_wait_for_target_agent", lambda *_args, **_kwargs: None)

    assert secure._spawn_target_agent(executable, "0.3.8", 8765) is process
    assert len(calls) == 2
    assert calls[0] & 0x01000000
    assert not (calls[1] & 0x01000000)


def test_install_update_does_not_create_unguarded_pre_msi_shutdown_gap(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    legacy = secure.legacy
    operation_id = "a" * 32
    msi = tmp_path / "candidate.msi"
    msi.write_bytes(b"candidate")
    expected_sha = legacy._sha256(msi)
    executable = _complete_install(tmp_path)
    (tmp_path / "Companion" / "current-version.txt").write_text("0.3.8", encoding="utf-8")

    monkeypatch.setattr(secure, "_maintenance_lock", lambda: nullcontext())
    monkeypatch.setattr(legacy, "_wait_parent", lambda _pid: None)
    monkeypatch.setattr(
        secure,
        "_stop_installed_processes",
        lambda *_args, **_kwargs: pytest.fail("in-app updater must let the MSI action own shutdown"),
    )
    monkeypatch.setattr(legacy, "_run_msiexec", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(secure, "_health_matches_target", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(legacy.subprocess, "Popen", lambda *_args, **_kwargs: object())

    secure.install_update(tmp_path, msi, expected_sha, "0.3.8", None, 8765, operation_id)

    assert executable.is_file()
    assert (tmp_path / "Cache" / "maintenance" / "last-update.json").is_file()


def test_secure_entry_replaces_legacy_dispatch_symbols():
    secure = _load_secure_module()
    assert secure.legacy.prepare_uninstall is secure.prepare_uninstall
    assert secure.legacy.install_update is secure.install_update
    assert secure.legacy.uninstall is secure.uninstall
