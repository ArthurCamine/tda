from __future__ import annotations

import json
from pathlib import Path

from tda_companion.maintenance_recovery import recover_interrupted_maintenance
from tda_companion.paths import CompanionPaths


def test_live_installation_guard_prevents_stale_journal_recovery(tmp_path: Path):
    paths = CompanionPaths.from_root(tmp_path / "TDA")
    version_root = paths.companion_root / "versions" / "0.3.8"
    executable = version_root / "TDACompanion.exe"
    maintenance = version_root / "TDACompanionMaintenance.exe"
    base_library = version_root / "_internal" / "base_library.zip"
    base_library.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"app")
    maintenance.write_bytes(b"maintenance")
    base_library.write_bytes(b"runtime")
    (paths.companion_root / "current-version.txt").write_text("0.3.8\n", encoding="utf-8")

    maintenance_root = paths.cache_root / "maintenance"
    maintenance_root.mkdir(parents=True, exist_ok=True)
    journal = maintenance_root / "last-operation.json"
    original = {
        "schema_version": 1,
        "operation_id": "a" * 32,
        "action": "update",
        "status": "running",
        "stage": "running_msi",
        "target_version": "0.3.8",
        "updated_at": 100.0,
    }
    journal.write_text(json.dumps(original), encoding="utf-8")
    (maintenance_root / "installation-guard.json").write_text("{}", encoding="utf-8")

    assert recover_interrupted_maintenance(paths, "0.3.8", executable, now=1000.0) is None
    assert json.loads(journal.read_text(encoding="utf-8")) == original
