from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .paths import CompanionPaths
from .single_active_version import installed_image_identity

_OPERATION_ID = re.compile(r"^[0-9a-f]{32}$")
_STALE_SECONDS = 120.0
_MAX_BYTES = 64 * 1024


def _read(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".recovery.{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def recover_interrupted_maintenance(
    paths: CompanionPaths,
    current_version: str,
    executable: Path,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Resolve a stale running journal from the installation state that survived.

    Windows Installer owns transaction rollback. If the maintenance helper dies
    after MSI commit, the new packaged app can prove that the target installation
    is present and close the journal as recovered. If the previous version is the
    one that survived, the journal is closed as failed/rolled back. Fresh journals
    are left untouched so a concurrently running helper is never second-guessed.
    """
    belongs, running_version = installed_image_identity(
        executable,
        paths.companion_root / "versions",
    )
    if not belongs or running_version != current_version:
        return None

    maintenance_root = paths.cache_root / "maintenance"
    last_path = maintenance_root / "last-operation.json"
    value = _read(last_path)
    if not value or value.get("status") != "running":
        return None

    operation_id = value.get("operation_id")
    action = value.get("action")
    stage = value.get("stage")
    updated_at = value.get("updated_at")
    if (
        not isinstance(operation_id, str)
        or _OPERATION_ID.fullmatch(operation_id) is None
        or action not in {"update", "uninstall"}
        or not isinstance(stage, str)
        or not isinstance(updated_at, (int, float))
        or isinstance(updated_at, bool)
    ):
        return None

    clock = time.time() if now is None else float(now)
    if clock - float(updated_at) < _STALE_SECONDS:
        return None

    recovered = dict(value)
    recovered["updated_at"] = clock
    recovered["failure_stage"] = None

    if action == "update":
        target_version = value.get("target_version")
        marker = paths.companion_root / "current-version.txt"
        try:
            installed_marker = marker.read_text(encoding="utf-8").strip()
        except OSError:
            installed_marker = ""
        target_executable = paths.companion_root / "versions" / current_version / "TDACompanion.exe"
        if (
            target_version == current_version
            and installed_marker == current_version
            and target_executable.is_file()
            and target_executable.resolve() == executable.resolve()
        ):
            recovered["status"] = "completed"
            recovered["stage"] = "recovered_after_interruption"
            recovered["error_code"] = None
            recovered["recovery"] = "target_installation_survived"
        else:
            recovered["status"] = "failed"
            recovered["stage"] = "failed"
            recovered["failure_stage"] = stage
            recovered["error_code"] = "UPDATE_INTERRUPTED_ROLLED_BACK"
            recovered["recovery"] = "running_version_survived"
    else:
        # If this packaged application can start, explicit uninstall did not
        # finish. Keep user data and close the stale operation deterministically.
        recovered["status"] = "failed"
        recovered["stage"] = "failed"
        recovered["failure_stage"] = stage
        recovered["error_code"] = "UNINSTALL_INTERRUPTED"
        recovered["recovery"] = "application_still_installed"

    operation_path = maintenance_root / "operations" / f"{operation_id}.json"
    _atomic_json(operation_path, recovered)
    _atomic_json(last_path, recovered)
    return recovered
