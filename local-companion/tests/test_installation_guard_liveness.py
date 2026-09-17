from __future__ import annotations

import json
import time
from pathlib import Path

import tda_companion.single_active_version as sav
from tda_companion.paths import CompanionPaths


def _paths(tmp_path: Path) -> CompanionPaths:
    return CompanionPaths.from_root(tmp_path / "TDA")


def _guard(paths: CompanionPaths, *, age_seconds: float) -> Path:
    path = paths.cache_root / "maintenance" / "installation-guard.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "tda_installation_guard_v1",
                "action": "major_upgrade",
                "target_version": "0.3.8",
                "created_at": time.time() - age_seconds,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_fresh_guard_survives_process_snapshot_race(tmp_path: Path, monkeypatch):
    paths = _paths(tmp_path)
    path = _guard(paths, age_seconds=1)
    monkeypatch.setattr(sav, "_guard_transaction_active", lambda: False)

    assert sav._active_installation_guard(paths) == ("major_upgrade", "0.3.8")
    assert path.is_file()


def test_guard_older_than_grace_is_removed_when_installer_is_gone(tmp_path: Path, monkeypatch):
    paths = _paths(tmp_path)
    path = _guard(paths, age_seconds=sav._INSTALL_GUARD_GRACE_SECONDS + 5)
    monkeypatch.setattr(sav, "_guard_transaction_active", lambda: False)

    assert sav._active_installation_guard(paths) is None
    assert not path.exists()


def test_guard_older_than_grace_remains_while_installer_is_active(tmp_path: Path, monkeypatch):
    paths = _paths(tmp_path)
    path = _guard(paths, age_seconds=sav._INSTALL_GUARD_GRACE_SECONDS + 5)
    monkeypatch.setattr(sav, "_guard_transaction_active", lambda: True)

    assert sav._active_installation_guard(paths) == ("major_upgrade", "0.3.8")
    assert path.is_file()
