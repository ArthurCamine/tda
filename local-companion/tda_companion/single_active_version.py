from __future__ import annotations

import json
import os
import re
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .paths import CompanionPaths

_VERSION_DIR = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_COMPANION_EXE = "tdacompanion.exe"
_RECONCILE_MUTEX = r"Local\TDACompanion.SingleActiveVersion"
_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_INSTALL_GUARD_SCHEMA = "tda_installation_guard_v1"
_INSTALL_GUARD_MAX_AGE_SECONDS = 60 * 60


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
    removed_update_cache_entries: tuple[str, ...] = ()
    removed_metadata_entries: tuple[str, ...] = ()
    redirect_executable: Path | None = None


@contextmanager
def _reconcile_lock(timeout_seconds: float = 15.0) -> Iterator[None]:
    """Serialize packaged repair between Startup, Agent and UI processes."""
    if os.name != "nt":
        yield
        return

    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, _RECONCILE_MUTEX)
    if not handle:
        raise SingleActiveVersionError("RECONCILE_LOCK_CREATE_FAILED")
    try:
        result = int(kernel32.WaitForSingleObject(handle, max(1, int(timeout_seconds * 1000))))
        if result not in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
            raise SingleActiveVersionError("RECONCILE_LOCK_TIMEOUT")
        try:
            yield
        finally:
            kernel32.ReleaseMutex(handle)
    finally:
        kernel32.CloseHandle(handle)


def _normalized_absolute(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).casefold()


def _version_tuple(value: str) -> tuple[int, int, int]:
    if _VERSION_DIR.fullmatch(value) is None:
        raise SingleActiveVersionError("TARGET_VERSION_INVALID")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _installation_guard_path(paths: CompanionPaths) -> Path:
    return paths.cache_root / "maintenance" / "installation-guard.json"


def _active_installation_guard(paths: CompanionPaths) -> tuple[str, str | None] | None:
    """Return a live MSI/maintenance guard, cleaning only stale/corrupt leftovers.

    The guard is a coordination primitive, not an authentication boundary. It
    prevents an old Startup/UI process from racing an MSI transaction after the
    old Agent was stopped but before Windows Installer has committed/rolled back.
    A target candidate may start during transactional verification; every other
    installed version must stand down.
    """
    path = _installation_guard_path(paths)
    try:
        if not path.is_file() or path.stat().st_size > 16 * 1024:
            if path.exists() and path.stat().st_size > 16 * 1024:
                path.unlink(missing_ok=True)
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != _INSTALL_GUARD_SCHEMA:
            raise ValueError("schema")
        action = value.get("action")
        target_version = value.get("target_version")
        created_at = value.get("created_at")
        if action not in {"major_upgrade", "uninstall"}:
            raise ValueError("action")
        if target_version is not None and (
            not isinstance(target_version, str) or _VERSION_DIR.fullmatch(target_version) is None
        ):
            raise ValueError("target")
        if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
            raise ValueError("created_at")
        age = time.time() - float(created_at)
        if age < -300 or age > _INSTALL_GUARD_MAX_AGE_SECONDS:
            path.unlink(missing_ok=True)
            return None
        return str(action), target_version
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def _valid_installed_versions(paths: CompanionPaths) -> dict[str, Path]:
    versions_root = paths.companion_root / "versions"
    result: dict[str, Path] = {}
    if not versions_root.is_dir():
        return result
    for entry in versions_root.iterdir():
        if not entry.is_dir() or _VERSION_DIR.fullmatch(entry.name) is None:
            continue
        executable = entry / "TDACompanion.exe"
        if executable.is_file():
            result[entry.name] = executable
    return result


def authoritative_installed_version(paths: CompanionPaths, running_version: str) -> tuple[str, Path]:
    """Never let an older executable downgrade a valid newer installation."""
    _version_tuple(running_version)
    installed = _valid_installed_versions(paths)
    running_executable = paths.companion_root / "versions" / running_version / "TDACompanion.exe"
    if running_version not in installed and running_executable.is_file():
        installed[running_version] = running_executable
    if not installed:
        raise SingleActiveVersionError("NO_VALID_INSTALLED_VERSION")
    active = max(installed, key=_version_tuple)
    return active, installed[active]


def _windows_process_image(pid: int) -> Path | None:
    """Query the OS image path without requiring the executable to exist on disk."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            length = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(length.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                return None
            value = buffer.value.strip()
            return Path(value) if value else None
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


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
    windows_image_lookup: Callable[[int], Path | None] = _windows_process_image,
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
        except (AttributeError, OSError, TypeError, ValueError):
            continue

        image = info.get("exe")
        if not image:
            try:
                image = process.exe()
            except (AttributeError, OSError, TypeError, ValueError):
                image = None
            except BaseException:
                image = None
        if not image:
            image = windows_image_lookup(pid)
        if not image:
            continue

        try:
            belongs, version = installed_image_identity(image, paths.companion_root / "versions")
        except (OSError, TypeError, ValueError):
            continue
        if belongs:
            result.append(InstalledCompanionProcess(pid=pid, image_path=Path(image), version=version))
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


def _current_process_image(pid: int) -> Path | None:
    image = _windows_process_image(pid)
    if image is not None:
        return image
    try:
        import psutil

        return Path(psutil.Process(pid).exe())
    except BaseException:
        return None


def _terminate_verified_installed_process(paths: CompanionPaths, observed: InstalledCompanionProcess) -> None:
    """Revalidate PID identity immediately before destructive termination."""
    current = _current_process_image(observed.pid)
    if current is None:
        raise SingleActiveVersionError("STALE_TDA_PROCESS_IDENTITY_UNVERIFIED")
    belongs, version = installed_image_identity(current, paths.companion_root / "versions")
    if (
        not belongs
        or version != observed.version
        or _normalized_absolute(current) != _normalized_absolute(observed.image_path)
    ):
        raise SingleActiveVersionError("STALE_TDA_PROCESS_IDENTITY_CHANGED")
    _terminate_pid(observed.pid)


def terminate_non_target_processes(
    paths: CompanionPaths,
    target_version: str,
    *,
    current_pid: int | None = None,
    scan: Callable[[], list[InstalledCompanionProcess]] | None = None,
    terminate_pid: Callable[[int], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, ...]:
    _version_tuple(target_version)

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
            if terminate_pid is None:
                _terminate_verified_installed_process(paths, process)
            else:
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


def _remove_with_retry(
    path: Path,
    *,
    remove_entry: Callable[[Path], None],
    sleep: Callable[[float], None],
    error_code: str,
) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    last_error: BaseException | None = None
    for attempt in range(4):
        try:
            remove_entry(path)
            if not path.exists() and not path.is_symlink():
                return True
        except (OSError, PermissionError) as exc:
            last_error = exc
        sleep(0.2 * (attempt + 1))
    raise SingleActiveVersionError(error_code) from last_error


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
        if _remove_with_retry(
            entry,
            remove_entry=remove_entry,
            sleep=sleep,
            error_code="STALE_VERSION_CLEANUP_FAILED",
        ):
            removed.append(entry.name)
    return tuple(removed)


def cleanup_installed_update_cache(
    paths: CompanionPaths,
    target_version: str,
    *,
    remove_entry: Callable[[Path], None] = _remove_entry,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, ...]:
    target = _version_tuple(target_version)
    updates_root = paths.cache_root / "updates"
    if not updates_root.is_dir():
        return ()

    removed: list[str] = []
    for entry in list(updates_root.iterdir()):
        if _VERSION_DIR.fullmatch(entry.name) is None:
            continue
        if _version_tuple(entry.name) > target:
            continue
        if _remove_with_retry(
            entry,
            remove_entry=remove_entry,
            sleep=sleep,
            error_code="STALE_UPDATE_CACHE_CLEANUP_FAILED",
        ):
            removed.append(entry.name)
    return tuple(removed)


def cleanup_stale_version_metadata(
    paths: CompanionPaths,
    *,
    remove_entry: Callable[[Path], None] = _remove_entry,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, ...]:
    root = paths.companion_root
    if not root.is_dir():
        return ()
    removed: list[str] = []
    for entry in list(root.glob("current-version.txt.partial.*")):
        if _remove_with_retry(
            entry,
            remove_entry=remove_entry,
            sleep=sleep,
            error_code="STALE_VERSION_METADATA_CLEANUP_FAILED",
        ):
            removed.append(entry.name)
    return tuple(removed)


def _write_current_version(paths: CompanionPaths, target_version: str) -> None:
    marker = paths.companion_root / "current-version.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_name(f"{marker.name}.partial.{os.getpid()}")
    try:
        temporary.write_text(target_version + "\n", encoding="utf-8")
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)


def reconcile_packaged_installation(
    paths: CompanionPaths,
    target_version: str,
    executable: Path,
    *,
    current_pid: int | None = None,
    scan: Callable[[], list[InstalledCompanionProcess]] | None = None,
    terminate_pid: Callable[[int], None] | None = None,
    remove_entry: Callable[[Path], None] = _remove_entry,
    sleep: Callable[[float], None] = time.sleep,
) -> ReconcileResult:
    """Converge an installed Companion to one active version without downgrading.

    Development/module execution is ignored. During a transactional upgrade only
    the candidate named by the installation guard may start, and it must not
    mutate MSI-owned version state before commit. Outside maintenance, the newest
    valid installed version is authoritative: launching an older binary redirects
    forward instead of deleting the newer installation.
    """

    belongs, running_version = installed_image_identity(
        executable,
        paths.companion_root / "versions",
    )
    if not belongs or running_version != target_version:
        return ReconcileResult(applied=False, target_version=target_version)

    guard = _active_installation_guard(paths)
    if guard is not None:
        action, guarded_target = guard
        if action == "major_upgrade" and guarded_target == running_version:
            return ReconcileResult(applied=False, target_version=target_version)
        raise SingleActiveVersionError("INSTALLATION_MAINTENANCE_ACTIVE")

    with _reconcile_lock():
        active_version, active_executable = authoritative_installed_version(paths, running_version)
        if _version_tuple(active_version) > _version_tuple(running_version):
            return ReconcileResult(
                applied=False,
                target_version=target_version,
                redirect_executable=active_executable,
            )

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
        removed_update_cache = cleanup_installed_update_cache(
            paths,
            target_version,
            remove_entry=remove_entry,
            sleep=sleep,
        )
        removed_metadata = cleanup_stale_version_metadata(
            paths,
            remove_entry=remove_entry,
            sleep=sleep,
        )
        return ReconcileResult(
            applied=True,
            target_version=target_version,
            terminated_pids=terminated,
            removed_entries=removed,
            removed_update_cache_entries=removed_update_cache,
            removed_metadata_entries=removed_metadata,
        )
