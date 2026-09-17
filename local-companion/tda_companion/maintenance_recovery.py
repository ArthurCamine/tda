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
_REQUIRED_TARGET_FILES = (
    "TDACompanion.exe",
    "TDACompanionMaintenance.exe",
    "_internal/base_library.zip",
)
# Only these running stages prove that msiexec already returned successfully.
# Earlier stages can describe a same-version repair that never actually ran, so
# filesystem equality alone must never turn them into a false success receipt.
_UPDATE_COMMIT_PROVABLE_STAGES = frozenset(
    {
        "verifying_install",
        "verifying_agent",
        "restarting_ui",
    }
)


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


def _complete_target_install(paths: CompanionPaths, version: str, executable: Path) -> bool:
    root = paths.companion_root / "versions" / version
    try:
        if not root.is_dir() or root.is_symlink():
            return False
        for relative in _REQUIRED_TARGET_FILES:
            path = root.joinpath(*relative.split("/"))
            if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
                return False
        return (root / "TDACompanion.exe").resolve() == executable.resolve()
    except OSError:
        return False


def recover_interrupted_maintenance(
    paths: CompanionPaths,
    current_version: str,
    executable: Path,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Resolve a stale running journal from the installation state that survived.

    Windows Installer owns transaction rollback. Recovery only closes an update
    as successful if a post-msiexec stage was reached *and* the surviving target
    is materially complete. A lone executable or torn version directory is never
    promoted to a success receipt.

    The packaged bootstrap runs during transactional candidate verification too.
    In that state the installation guard is authoritative: a long-running MSI may
    legitimately leave the updater journal at ``running_msi`` for more than the
    stale threshold, so recovery must not second-guess it until the guard is gone.
    """
    belongs, running_version = installed_image_identity(
        executable,
        paths.companion_root / "versions",
    )
    if not belongs or running_version != current_version:
        return None

    maintenance_root = paths.cache_root / "maintenance"
    if (maintenance_root / "installation-guard.json").is_file():
        return None

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
        except (OSError, UnicodeError):
            installed_marker = ""
        target_survived = bool(
            target_version == current_version
            and installed_marker == current_version
            and _complete_target_install(paths, current_version, executable)
        )

        if target_survived and stage in _UPDATE_COMMIT_PROVABLE_STAGES:
            recovered["status"] = "completed"
            recovered["stage"] = "recovered_after_interruption"
            recovered["error_code"] = None
            recovered["recovery"] = "target_installation_survived"
        elif target_survived:
            recovered["status"] = "failed"
            recovered["stage"] = "failed"
            recovered["failure_stage"] = stage
            recovered["error_code"] = "UPDATE_INTERRUPTED_UNVERIFIED"
            recovered["recovery"] = "target_present_but_completion_unproven"
        else:
            recovered["status"] = "failed"
            recovered["stage"] = "failed"
            recovered["failure_stage"] = stage
            recovered["error_code"] = "UPDATE_INTERRUPTED_ROLLED_BACK"
            recovered["recovery"] = "running_version_survived_or_target_incomplete"
    else:
        recovered["status"] = "failed"
        recovered["stage"] = "failed"
        recovered["failure_stage"] = stage
        recovered["error_code"] = "UNINSTALL_INTERRUPTED"
        recovered["recovery"] = "application_still_installed"

    operation_path = maintenance_root / "operations" / f"{operation_id}.json"
    _atomic_json(operation_path, recovered)
    _atomic_json(last_path, recovered)
    return recovered
