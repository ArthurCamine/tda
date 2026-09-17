from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .paths import CompanionPaths

_VERSION_DIR = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_COMPANION_EXE = "tdacompanion.exe"


class SingleActiveVersionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class InstalledCompanionProcess:
    pid: int
    image_path: Path
    version: str | None


@dataclass(frozen=True)
class ReconcileResult:
    applied: bool
    target_version: str
    terminated_pids: tuple[int, ...] = ()
    removed_entries: tuple[str, ...] = ()


def _normalized_absolute(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).casefold()


def installed_image_identity(
    image_path: str | Path,
    versions_root: Path,
) -> tuple[bool, str | None]:
    """Classify a running image without requiring the file to still exist.

    Recovery deliberately uses lexical containment here. A process can remain
    alive after an upgrade has already removed its executable from disk; strict
    filesystem resolution would make exactly that broken state impossible to
    repair. This function is only for deciding whether a process belongs to the
    per-user TDA install and may be stopped. Authenticated Agent communication
    continues to use the stricter loopback-owner verification.
    """

    root = _normalized_absolute(versions_root).rstrip("\\/")
    actual = _normalized_absolute(image_path)
    prefix = root + os.sep.casefold()
    if not actual.startswith(prefix):
        return False, None

    relative = actual[len(prefix) :]
    parts = tuple(part for part in re.split(r"[\\/]", relative) if part)
    if len(parts) != 2 or parts[1].casefold() != _COMPANION_EXE:
        return False, None

    version = parts[0] if _VERSION_DIR.fullmatch(parts[0]) else None
    return True, version


def scan_installed_companion_processes(
    paths: CompanionPaths,
    *,
    process_iter: Callable[[], Iterable[Any]] | None = None,
) -> list[InstalledCompanionProcess]:
    if process_iter is None:
        try:
            import psutil
        except ImportError as exc:
            raise SingleActiveVersionError("PROCESS_INSPECTION_UNAVAILABLE") from exc
        process_iter = lambda: psutil.process_iter(["pid", "name", "exe"])

    result: list[InstalledCompanionProcess] = []
    try:
        processes = process_iter()
    except BaseException as exc:
        raise SingleActiveVersionError("PROCESS_ENUMERATION_FAILED") from exc

    for process in processes:
        try:
            info = getattr(process, "info", {}) or {}
            pid = int(info.get("pid") or getattr(process, "pid"))
            image = info.get("exe")
            if not image:
                image = process.exe()
            if not image:
                continue
            belongs, version = installed_image_identity(image, paths.companion_root / "versions")
            if belongs:
                result.append(InstalledCompanionProcess(pid=pid, image_path=Path(image), version=version))
        except (AttributeError, OSError, TypeError, ValueError):
            continue
        except BaseException:
            # Process tables are inherently racy. A process disappearing while
            # being inspected is not an installation failure.
            continue
    return result


def _terminate_pid(pid: int) -> None:
    try:
        import psutil
    except ImportError as exc:
        raise SingleActiveVersionError("PROCESS_TERMINATION_UNAVAILABLE") from exc

    try:
        process = psutil.Process(pid)
        process.terminate()
        try:
            process.wait(timeout=1.5)
            return
        except psutil.TimeoutExpired:
            process.kill()
            process.wait(timeout=3.0)
    except psutil.NoSuchProcess:
        return
    except (psutil.AccessDenied, OSError) as exc:
        raise SingleActiveVersionError("STALE_TDA_PROCESS_TERMINATION_FAILED") from exc


def terminate_non_target_processes(
    paths: CompanionPaths,
    target_version: str,
    *,
    current_pid: int | None = None,
    scan: Callable[[], list[InstalledCompanionProcess]] | None = None,
    terminate_pid: Callable[[int], None] = _terminate_pid,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, ...]:
    if _VERSION_DIR.fullmatch(target_version) is None:
        raise SingleActiveVersionError("TARGET_VERSION_INVALID")

    current_pid = os.getpid() if current_pid is None else int(current_pid)
    scan = scan or (lambda: scan_installed_companion_processes(paths))
    terminated: list[int] = []

    # Re-scan after every round. This both proves the post-condition and catches
    # an old Startup entry racing the new process during recovery.
    for attempt in range(3):
        stale = [
            process
            for process in scan()
            if process.pid != current_pid and process.version != target_version
        ]
        if not stale:
            return tuple(dict.fromkeys(terminated))
        for process in stale:
            terminate_pid(process.pid)
            terminated.append(process.pid)
        sleep(0.15 * (attempt + 1))

    remaining = [
        process
        for process in scan()
        if process.pid != current_pid and process.version != target_version
    ]
    if remaining:
        raise SingleActiveVersionError("STALE_TDA_PROCESS_STILL_RUNNING")
    return tuple(dict.fromkeys(terminated))


def _remove_entry(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def cleanup_non_target_versions(
    paths: CompanionPaths,
    target_version: str,
    *,
    remove_entry: Callable[[Path], None] = _remove_entry,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, ...]:
    versions_root = paths.companion_root / "versions"
    target = versions_root / target_version
    target_executable = target / "TDACompanion.exe"
    if not target_executable.is_file():
        raise SingleActiveVersionError("TARGET_EXECUTABLE_MISSING")

    removed: list[str] = []
    for entry in list(versions_root.iterdir()) if versions_root.is_dir() else []:
        if entry.name == target_version:
            continue
        last_error: BaseException | None = None
        for attempt in range(4):
            try:
                remove_entry(entry)
                if not entry.exists():
                    removed.append(entry.name)
                    last_error = None
                    break
            except (OSError, PermissionError) as exc:
                last_error = exc
            sleep(0.2 * (attempt + 1))
        if last_error is not None or entry.exists():
            raise SingleActiveVersionError("STALE_VERSION_CLEANUP_FAILED") from last_error
    return tuple(removed)


def _write_current_version(paths: CompanionPaths, target_version: str) -> None:
    marker = paths.companion_root / "current-version.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_name(marker.name + ".partial")
    temporary.write_text(target_version + "\n", encoding="utf-8")
    os.replace(temporary, marker)


def reconcile_packaged_installation(
    paths: CompanionPaths,
    target_version: str,
    executable: Path,
    *,
    current_pid: int | None = None,
    scan: Callable[[], list[InstalledCompanionProcess]] | None = None,
    terminate_pid: Callable[[int], None] = _terminate_pid,
    remove_entry: Callable[[Path], None] = _remove_entry,
    sleep: Callable[[float], None] = time.sleep,
) -> ReconcileResult:
    """Converge an installed Companion to one active version.

    Development/module execution is intentionally ignored. For a packaged build
    the current executable must itself be the target executable under
    Companion/versions/<semver>; only then may this routine kill old TDA
    processes or remove old version directories.
    """

    belongs, running_version = installed_image_identity(
        executable,
        paths.companion_root / "versions",
    )
    if not belongs or running_version != target_version:
        return ReconcileResult(applied=False, target_version=target_version)

    terminated = terminate_non_target_processes(
        paths,
        target_version,
        current_pid=current_pid,
        scan=scan,
        terminate_pid=terminate_pid,
        sleep=sleep,
    )
    removed = cleanup_non_target_versions(
        paths,
        target_version,
        remove_entry=remove_entry,
        sleep=sleep,
    )
    _write_current_version(paths, target_version)
    return ReconcileResult(
        applied=True,
        target_version=target_version,
        terminated_pids=terminated,
        removed_entries=removed,
    )
