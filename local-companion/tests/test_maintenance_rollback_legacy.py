from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


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
    for name in ("maintenance_entry", "tda_companion_maintenance_rollback_legacy_test"):
        sys.modules.pop(name, None)
    path = packaging / "maintenance_secure_entry.py"
    spec = importlib.util.spec_from_file_location(
        "tda_companion_maintenance_rollback_legacy_test",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_install(root: Path, version: str = "0.3.4") -> Path:
    version_root = root / "Companion" / "versions" / version
    executable = version_root / "TDACompanion.exe"
    base_library = version_root / "_internal" / "base_library.zip"
    base_library.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"legacy-app")
    base_library.write_bytes(b"legacy-runtime")
    marker = root / "Companion" / "current-version.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(version + "\n", encoding="utf-8")
    return executable


def test_historical_rollback_payload_is_restorable_without_new_maintenance_helper(tmp_path: Path):
    secure = _load_secure_module()
    executable = _legacy_install(tmp_path)

    assert secure._complete_installed_version(tmp_path, "0.3.4") is False
    assert secure._restorable_installed_version(tmp_path, "0.3.4") is True
    assert secure._surviving_install(tmp_path) == ("0.3.4", executable)


def test_historical_rollback_still_requires_real_pyinstaller_payload(tmp_path: Path):
    secure = _load_secure_module()
    executable = _legacy_install(tmp_path)
    (executable.parent / "_internal" / "base_library.zip").unlink()

    assert secure._restorable_installed_version(tmp_path, "0.3.4") is False
    assert secure._surviving_install(tmp_path) is None


def test_rollback_restart_uses_restored_historical_agent_only_after_identity_checks(tmp_path: Path, monkeypatch):
    secure = _load_secure_module()
    executable = _legacy_install(tmp_path)
    spawned: list[tuple[Path, str, int]] = []

    monkeypatch.setattr(secure, "_health_matches_target", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(secure, "_port_is_free", lambda _port: True)
    monkeypatch.setattr(
        secure,
        "_spawn_target_agent",
        lambda exe, version, port: spawned.append((exe, version, port)),
    )

    assert secure._restart_surviving_agent(tmp_path, 8765) == executable
    assert spawned == [(executable, "0.3.4", 8765)]
