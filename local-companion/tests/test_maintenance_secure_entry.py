from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

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

    def terminate(pid: int):
        terminated.append(pid)
        alive.discard(pid)

    monkeypatch.setattr(legacy, "_terminate_pid", terminate)
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


def test_major_upgrade_stops_old_processes_and_proves_port_free(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    legacy = secure.legacy
    alive = {222}
    terminated: list[int] = []
    port_checks: list[int] = []

    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: (sorted(alive), []))

    def terminate(pid: int):
        terminated.append(pid)
        alive.discard(pid)

    monkeypatch.setattr(legacy, "_terminate_pid", terminate)
    monkeypatch.setattr(secure.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(secure, "_wait_port_free", lambda port: port_checks.append(port))

    secure.prepare_major_upgrade(tmp_path, 8765)

    assert terminated == [222]
    assert alive == set()
    assert port_checks == [8765]


def test_explicit_uninstall_does_not_block_on_unrelated_listener(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: ([], []))
    monkeypatch.setattr(
        secure,
        "_wait_port_free",
        lambda _port: pytest.fail("explicit uninstall must not depend on unrelated Agent port ownership"),
    )

    secure.prepare_uninstall(tmp_path, 8765)


def test_major_upgrade_cli_is_owned_by_secure_wrapper(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    observed: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        secure,
        "prepare_major_upgrade",
        lambda root, port=8765: observed.append((root, port)),
    )
    monkeypatch.setattr(
        secure.legacy,
        "main",
        lambda _argv: pytest.fail("legacy parser must not receive --prepare-major-upgrade"),
    )

    assert secure.main(["--prepare-major-upgrade", "--root", str(tmp_path), "--port", "9876"]) == 0
    assert observed == [(tmp_path.resolve(), 9876)]


def test_secure_maintenance_fails_closed_when_old_process_survives(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    legacy = secure.legacy

    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: ([222], []))
    monkeypatch.setattr(legacy, "_terminate_pid", lambda _pid: None)
    monkeypatch.setattr(secure.time, "sleep", lambda _seconds: None)

    with pytest.raises(legacy.MaintenanceError, match="TDA_PROCESS_STILL_RUNNING"):
        secure.prepare_uninstall(tmp_path, 8765)


def test_secure_maintenance_fails_closed_when_process_identity_is_unreadable(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    legacy = secure.legacy

    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: ([], [9320]))
    monkeypatch.setattr(
        legacy,
        "_terminate_pid",
        lambda _pid: pytest.fail("unverified same-name process must never be killed blindly"),
    )

    with pytest.raises(legacy.MaintenanceError, match="TDA_PROCESS_IDENTITY_UNVERIFIED"):
        secure.prepare_major_upgrade(tmp_path, 8765)


def test_major_upgrade_fails_closed_when_agent_port_never_frees(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    legacy = secure.legacy

    monkeypatch.setattr(secure, "_scan_tda_processes", lambda _root: ([], []))
    monkeypatch.setattr(secure, "_port_is_free", lambda _port: False)
    monkeypatch.setattr(secure.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 10.0])
    monkeypatch.setattr(secure.time, "monotonic", lambda: next(ticks, 10.0))

    with pytest.raises(legacy.MaintenanceError, match="AGENT_PORT_STILL_OCCUPIED"):
        secure.prepare_major_upgrade(tmp_path, 8765)


def test_secure_entry_replaces_legacy_dispatch_symbols():
    secure = _load_secure_module()
    assert secure.legacy.prepare_uninstall is secure.prepare_uninstall
    assert secure.legacy.install_update is secure.install_update
