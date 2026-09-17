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


def test_secure_maintenance_never_reads_or_posts_pairing_token(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    legacy = secure.legacy
    removed: list[bool] = []
    terminated: list[int] = []
    alive = {111, 222}

    monkeypatch.setattr(legacy, "_remove_startup_value", lambda: removed.append(True))
    monkeypatch.setattr(legacy, "_installed_companion_pids", lambda _root: sorted(alive))
    monkeypatch.setattr(secure.os, "getpid", lambda: 111)

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

    assert removed == [True]
    assert terminated == [222]
    assert alive == {111}


def test_secure_maintenance_fails_closed_when_old_process_survives(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    legacy = secure.legacy

    monkeypatch.setattr(legacy, "_remove_startup_value", lambda: None)
    monkeypatch.setattr(legacy, "_installed_companion_pids", lambda _root: [222])
    monkeypatch.setattr(secure.os, "getpid", lambda: 111)
    monkeypatch.setattr(legacy, "_terminate_pid", lambda _pid: None)
    monkeypatch.setattr(secure.time, "sleep", lambda _seconds: None)

    with pytest.raises(legacy.MaintenanceError, match="TDA_PROCESS_STILL_RUNNING"):
        secure.prepare_uninstall(tmp_path, 8765)


def test_secure_entry_replaces_legacy_dispatch_symbols():
    secure = _load_secure_module()
    assert secure.legacy.prepare_uninstall is secure.prepare_uninstall
    assert secure.legacy.install_update is secure.install_update
