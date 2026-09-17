from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import maintenance_entry as legacy
import psutil

_INSTALL_GUARD_SCHEMA = "tda_installation_guard_v1"
_INSTALL_GUARD_MAX_AGE_SECONDS = 60 * 60
_MAINTENANCE_MUTEX = r"Local\Faysk.TDA.Companion.MaintenanceTransaction"
# This deliberately matches installation_lock._INSTALLATION_MUTEX. The outer
# packaged bootstrap lock must be shared with maintenance so no UI/Startup
# process can enter reconciliation between creation of the MSI guard and process
# quiescence.
_RECONCILE_MUTEX = r"Local\Faysk.TDA.Companion.InstallationReconcile"
_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_TIMEOUT = 0x00000102
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_REQUIRED_VERSION_FILES = (
    "TDACompanion.exe",
    "TDACompanionMaintenance.exe",
    "_internal/base_library.zip",
)
# Rollback may restore a historical Companion released before the standalone
# maintenance helper existed. Such a product is valid enough to revive only
# when its original executable plus PyInstaller runtime payload were restored.
# New candidate verification remains intentionally stricter above.
_RESTORABLE_VERSION_FILES = (
    "TDACompanion.exe",
    "_internal/base_library.zip",
)


@contextmanager
def _named_lock(name: str, timeout_seconds: float, error_prefix: str):
    if os.name != "nt":
        yield
        return
    kernel32 = legacy.ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise legacy.MaintenanceError(f"{error_prefix}_CREATE_FAILED")
    acquired = False
    try:
        result = int(kernel32.WaitForSingleObject(handle, max(1, int(timeout_seconds * 1000))))
        if result in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
            acquired = True
            yield
            return
        if result == _WAIT_TIMEOUT:
            raise legacy.MaintenanceError(f"{error_prefix}_TIMEOUT")
        raise legacy.MaintenanceError(f"{error_prefix}_WAIT_FAILED")
    finally:
        if acquired:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


@contextmanager
def _maintenance_lock(timeout_seconds: float = 30.0):
    with _named_lock(_MAINTENANCE_MUTEX, timeout_seconds, "MAINTENANCE_LOCK"):
        yield


@contextmanager
def _installation_reconcile_lock(timeout_seconds: float = 30.0):
    with _named_lock(_RECONCILE_MUTEX, timeout_seconds, "INSTALLATION_LOCK"):
        yield


def _guard_path(root: Path) -> Path:
    return root / "Cache" / "maintenance" / "installation-guard.json"


def _read_guard(root: Path) -> dict[str, object] | None:
    path = _guard_path(root)
    try:
        if not path.is_file() or path.stat().st_size > 16 * 1024:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != _INSTALL_GUARD_SCHEMA:
        return None
    created_at = value.get("created_at")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        return None
    age = time.time() - float(created_at)
    if age < -300 or age > _INSTALL_GUARD_MAX_AGE_SECONDS:
        return None
    return value


def _begin_guard(root: Path, action: str, target_version: str | None) -> None:
    if action not in {"major_upgrade", "uninstall"}:
        raise legacy.MaintenanceError("INSTALLATION_GUARD_ACTION_INVALID")
    if target_version is not None and _VERSION.fullmatch(target_version) is None:
        raise legacy.MaintenanceError("INSTALLATION_GUARD_VERSION_INVALID")
    existing = _read_guard(root)
    if existing is not None and (
        existing.get("action") != action or existing.get("target_version") != target_version
    ):
        raise legacy.MaintenanceError("INSTALLATION_MAINTENANCE_ACTIVE")

    path = _guard_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    value = {
        "schema": _INSTALL_GUARD_SCHEMA,
        "action": action,
        "target_version": target_version,
        "created_at": time.time(),
    }
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _clear_guard(root: Path) -> None:
    try:
        _guard_path(root).unlink(missing_ok=True)
    except OSError:
        pass


def _normalized(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).casefold()


def _installed_image_version(root: Path, image: str | Path) -> str | None:
    """Accept only <root>/Companion/versions/<semver>/TDACompanion.exe."""
    versions = _normalized(root / "Companion" / "versions").rstrip("\\/")
    actual = _normalized(image)
    prefix = versions + os.sep.casefold()
    if not actual.startswith(prefix):
        return None
    relative = actual[len(prefix) :]
    parts = tuple(part for part in re.split(r"[\\/]", relative) if part)
    if (
        len(parts) != 2
        or _VERSION.fullmatch(parts[0]) is None
        or parts[1].casefold() != "tdacompanion.exe"
    ):
        return None
    return parts[0]


def _version_has_files(root: Path, version: str, required: tuple[str, ...]) -> bool:
    if _VERSION.fullmatch(version) is None:
        return False
    version_root = root / "Companion" / "versions" / version
    try:
        if not version_root.is_dir() or version_root.is_symlink():
            return False
        for relative in required:
            path = version_root.joinpath(*relative.split("/"))
            if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
                return False
        return True
    except OSError:
        return False


def _complete_installed_version(root: Path, version: str) -> bool:
    return _version_has_files(root, version, _REQUIRED_VERSION_FILES)


def _restorable_installed_version(root: Path, version: str) -> bool:
    """Accept the minimum payload shared by historical packaged releases.

    This predicate is only used after MSI rollback to revive the product Windows
    Installer restored. It must never be used to validate a newly installed
    target, whose maintenance helper is part of the current release contract.
    """
    return _version_has_files(root, version, _RESTORABLE_VERSION_FILES)


def _scan_tda_processes(root: Path) -> tuple[list[int], list[int]]:
    if os.name != "nt":
        return legacy._installed_companion_pids(root), []

    kernel32 = legacy.ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(legacy.TH32CS_SNAPPROCESS, 0)
    if snapshot == legacy.INVALID_HANDLE_VALUE:
        raise legacy.MaintenanceError("TDA_PROCESS_SCAN_FAILED")

    installed: list[int] = []
    unresolved: list[int] = []
    entry = legacy.PROCESSENTRY32W()
    entry.dwSize = legacy.ctypes.sizeof(legacy.PROCESSENTRY32W)
    try:
        ok = kernel32.Process32FirstW(snapshot, legacy.ctypes.byref(entry))
        if not ok:
            raise legacy.MaintenanceError("TDA_PROCESS_SCAN_FAILED")
        while ok:
            if entry.szExeFile.casefold() == "tdacompanion.exe":
                pid = int(entry.th32ProcessID)
                if pid != os.getpid():
                    image = legacy._process_image(pid)
                    if image is None:
                        unresolved.append(pid)
                    elif _installed_image_version(root, image) is not None:
                        installed.append(pid)
            ok = kernel32.Process32NextW(snapshot, legacy.ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return sorted(set(installed)), sorted(set(unresolved))


def _other_installed_pids(root: Path) -> list[int]:
    installed, unresolved = _scan_tda_processes(root)
    if unresolved:
        raise legacy.MaintenanceError("TDA_PROCESS_IDENTITY_UNVERIFIED")
    return [pid for pid in installed if pid != os.getpid()]


def _verified_process_image(root: Path, pid: int) -> Path:
    image = legacy._process_image(pid)
    if image is None:
        raise legacy.MaintenanceError("TDA_PROCESS_IDENTITY_UNVERIFIED")
    if _installed_image_version(root, image) is None:
        raise legacy.MaintenanceError("TDA_PROCESS_IDENTITY_CHANGED")
    return image


def _terminate_verified_pid(root: Path, pid: int) -> None:
    _verified_process_image(root, pid)
    legacy._terminate_pid(pid)


def _port_is_free(port: int) -> bool:
    if not 1024 <= int(port) <= 65535:
        raise legacy.MaintenanceError("AGENT_PORT_INVALID")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _wait_port_free(port: int, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_is_free(port):
            return
        time.sleep(0.1)
    if _port_is_free(port):
        return
    raise legacy.MaintenanceError("AGENT_PORT_STILL_OCCUPIED")


def _stop_installed_processes(
    root: Path,
    *,
    port: int | None = None,
    require_port_free: bool = False,
) -> None:
    for attempt in range(4):
        remaining = _other_installed_pids(root)
        if not remaining:
            break
        for pid in remaining:
            _terminate_verified_pid(root, pid)
        time.sleep(0.2 * (attempt + 1))

    if _other_installed_pids(root):
        raise legacy.MaintenanceError("TDA_PROCESS_STILL_RUNNING")
    if require_port_free:
        if port is None:
            raise legacy.MaintenanceError("AGENT_PORT_REQUIRED")
        _wait_port_free(port)


def prepare_major_upgrade(root: Path, port: int = 8765, target_version: str | None = None) -> None:
    with _installation_reconcile_lock():
        _begin_guard(root, "major_upgrade", target_version)
        try:
            _stop_installed_processes(root, port=port, require_port_free=True)
        except BaseException:
            _clear_guard(root)
            raise


def prepare_explicit_uninstall(root: Path) -> None:
    with _installation_reconcile_lock():
        _begin_guard(root, "uninstall", None)
        try:
            _stop_installed_processes(root)
        except BaseException:
            _clear_guard(root)
            raise


def prepare_uninstall(root: Path, port: int = 8765) -> None:
    del port
    with _installation_reconcile_lock():
        _stop_installed_processes(root)


def finish_major_upgrade(root: Path) -> None:
    _clear_guard(root)


def rollback_major_upgrade(root: Path, port: int = 8765) -> None:
    try:
        with _installation_reconcile_lock():
            _stop_installed_processes(root)
    finally:
        _clear_guard(root)
    _restart_surviving_agent(root, port)


def _target_health(port: int) -> dict[str, object] | None:
    request = legacy.urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/health",
        headers={"Accept": "application/json", "Cache-Control": "no-store"},
        method="GET",
    )
    try:
        with legacy._loopback_opener().open(request, timeout=0.4) as response:
            if response.status != 200:
                return None
            raw = response.read(64 * 1024 + 1)
            if len(raw) > 64 * 1024:
                return None
            value = legacy.json.loads(raw.decode("utf-8")) if raw else {}
            return value if isinstance(value, dict) else None
    except Exception:
        return None


def _listener_owned_by(port: int, pid: int) -> bool:
    try:
        owners: set[int] = set()
        for connection in psutil.net_connections(kind="tcp"):
            status = str(getattr(connection, "status", "") or "").upper()
            address = getattr(connection, "laddr", None)
            owner = getattr(connection, "pid", None)
            if status != "LISTEN" or address is None:
                continue
            if hasattr(address, "ip") and hasattr(address, "port"):
                host, local_port = str(address.ip), int(address.port)
            elif len(address) >= 2:
                host, local_port = str(address[0]), int(address[1])
            else:
                continue
            if host == "127.0.0.1" and local_port == port and isinstance(owner, int) and owner > 0:
                owners.add(owner)
        return owners == {pid}
    except BaseException:
        return False


def _health_matches_target(
    executable: Path,
    expected_version: str,
    port: int,
    *,
    expected_pid: int | None = None,
) -> bool:
    health = _target_health(port)
    if health is None:
        return False
    pid = health.get("pid")
    if not isinstance(pid, int) or pid <= 0 or not _listener_owned_by(port, pid):
        return False
    image = legacy._process_image(pid)
    if image is None:
        return False
    try:
        expected_image = os.path.normcase(str(executable.resolve())).casefold()
        actual_image = os.path.normcase(str(image)).casefold()
    except OSError:
        return False
    return bool(
        health.get("product_id") == "tda-companion"
        and str(health.get("api_version") or "") == "1"
        and health.get("service_version") == expected_version
        and health.get("port") == port
        and (expected_pid is None or pid == expected_pid)
        and actual_image == expected_image
    )


def _wait_for_target_agent(
    executable: Path,
    expected_version: str,
    port: int,
    process,
    *,
    timeout: float = 15.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise legacy.MaintenanceError("UPDATED_AGENT_EXITED")
        if _health_matches_target(
            executable,
            expected_version,
            port,
            expected_pid=getattr(process, "pid", None),
        ):
            return
        time.sleep(0.15)
    raise legacy.MaintenanceError("UPDATED_AGENT_NOT_READY")


def _spawn_target_agent(executable: Path, expected_version: str, port: int):
    base_flags = (
        getattr(legacy.subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(legacy.subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    breakaway = getattr(legacy.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    command = [str(executable), "--agent", "--startup"]
    kwargs = {
        "stdin": legacy.subprocess.DEVNULL,
        "stdout": legacy.subprocess.DEVNULL,
        "stderr": legacy.subprocess.DEVNULL,
        "close_fds": True,
    }
    try:
        process = legacy.subprocess.Popen(
            command,
            creationflags=base_flags | breakaway,
            **kwargs,
        )
    except OSError:
        if not breakaway:
            raise
        process = legacy.subprocess.Popen(command, creationflags=base_flags, **kwargs)
    _wait_for_target_agent(executable, expected_version, port, process)
    return process


def verify_installed_target(root: Path, expected_version: str, port: int = 8765) -> None:
    if _VERSION.fullmatch(expected_version) is None:
        raise legacy.MaintenanceError("UPDATE_VERSION_INVALID")
    if not _complete_installed_version(root, expected_version):
        raise legacy.MaintenanceError("UPDATED_INSTALLATION_INCOMPLETE")
    executable = root / "Companion" / "versions" / expected_version / "TDACompanion.exe"
    if _health_matches_target(executable, expected_version, port):
        return
    if not _port_is_free(port):
        raise legacy.MaintenanceError("AGENT_PORT_STILL_OCCUPIED")
    _spawn_target_agent(executable, expected_version, port)


def _surviving_install(root: Path) -> tuple[str, Path] | None:
    marker = root / "Companion" / "current-version.txt"
    try:
        version = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not _restorable_installed_version(root, version):
        return None
    return version, root / "Companion" / "versions" / version / "TDACompanion.exe"


def _restart_surviving_agent(root: Path, port: int) -> Path | None:
    surviving = _surviving_install(root)
    if surviving is None:
        return None
    version, executable = surviving
    try:
        if not _health_matches_target(executable, version, port):
            if not _port_is_free(port):
                return None
            _spawn_target_agent(executable, version, port)
        return executable
    except BaseException:
        return None


def _restart_surviving_install(root: Path, port: int) -> None:
    executable = _restart_surviving_agent(root, port)
    if executable is None:
        return
    try:
        legacy.subprocess.Popen([str(executable), "--ui"], close_fds=True)
    except BaseException:
        return


def install_update(
    root: Path,
    msi: Path,
    expected_sha256: str,
    expected_version: str,
    parent_pid: int | None,
    port: int,
    operation_id: str | None = None,
) -> None:
    with _maintenance_lock():
        operation_id = legacy._normalize_operation_id(operation_id)
        journal = legacy.MaintenanceJournal(
            root,
            operation_id,
            "update",
            metadata={
                "target_version": expected_version,
                "expected_sha256": expected_sha256.casefold(),
            },
        )
        log_path = legacy._msi_log_path(root, operation_id)
        try:
            journal.stage("waiting_for_ui_exit")
            legacy._wait_parent(parent_pid)

            journal.stage("verifying_asset")
            if not msi.is_file() or legacy._sha256(msi).casefold() != expected_sha256.casefold():
                raise legacy.MaintenanceError("UPDATE_HASH_MISMATCH")

            journal.stage("running_msi")
            msi_exit_code = legacy._run_msiexec(["/i", str(msi), "/passive"], log_path)
            journal.stage("verifying_install", msi_exit_code=msi_exit_code)

            marker = root / "Companion" / "current-version.txt"
            installed = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
            if installed != expected_version:
                raise legacy.MaintenanceError("UPDATE_VERSION_MISMATCH")
            if not _complete_installed_version(root, expected_version):
                raise legacy.MaintenanceError("UPDATED_INSTALLATION_INCOMPLETE")
            executable = root / "Companion" / "versions" / expected_version / "TDACompanion.exe"

            journal.stage("verifying_agent")
            if not _health_matches_target(executable, expected_version, port):
                if not _port_is_free(port):
                    raise legacy.MaintenanceError("AGENT_PORT_STILL_OCCUPIED")
                _spawn_target_agent(executable, expected_version, port)

            journal.stage("restarting_ui")
            legacy.subprocess.Popen([str(executable), "--ui"], close_fds=True)

            journal.complete(msi_exit_code=msi_exit_code, installed_version=expected_version)
            try:
                legacy._write_receipt(
                    root,
                    "last-update.json",
                    {
                        "operation_id": operation_id,
                        "version": expected_version,
                        "sha256": expected_sha256.casefold(),
                        "status": "installed",
                        "msi_exit_code": msi_exit_code,
                        "msi_log": str(Path("Cache") / "maintenance" / "logs" / f"{operation_id}.msi.log"),
                        "at": time.time(),
                    },
                )
            except OSError:
                pass
        except BaseException as exc:
            journal.fail(exc)
            _restart_surviving_install(root, port)
            raise


_legacy_uninstall = legacy.uninstall


def uninstall(
    root: Path,
    *,
    purge: bool,
    parent_pid: int | None,
    port: int,
    operation_id: str | None = None,
) -> None:
    with _maintenance_lock():
        _begin_guard(root, "uninstall", None)
        try:
            _legacy_uninstall(
                root,
                purge=purge,
                parent_pid=parent_pid,
                port=port,
                operation_id=operation_id,
            )
        finally:
            _clear_guard(root)


legacy.prepare_uninstall = prepare_uninstall
legacy.install_update = install_update
legacy.uninstall = uninstall


def _secure_msi_action_main(argv: list[str]) -> int | None:
    secure_flags = {
        "--prepare-major-upgrade",
        "--prepare-explicit-uninstall",
        "--finish-major-upgrade",
        "--rollback-major-upgrade",
        "--verify-installed-target",
    }
    if not any(flag in argv for flag in secure_flags):
        return None

    parser = argparse.ArgumentParser(add_help=False)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--prepare-major-upgrade", action="store_true")
    actions.add_argument("--prepare-explicit-uninstall", action="store_true")
    actions.add_argument("--finish-major-upgrade", action="store_true")
    actions.add_argument("--rollback-major-upgrade", action="store_true")
    actions.add_argument("--verify-installed-target", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--target-version")
    try:
        args = parser.parse_args(argv)
        root = (args.root or legacy.local_root()).resolve()
        if args.prepare_major_upgrade:
            prepare_major_upgrade(root, args.port, args.target_version)
        elif args.prepare_explicit_uninstall:
            prepare_explicit_uninstall(root)
        elif args.finish_major_upgrade:
            finish_major_upgrade(root)
        elif args.rollback_major_upgrade:
            rollback_major_upgrade(root, args.port)
        else:
            if not args.target_version:
                raise legacy.MaintenanceError("UPDATE_VERSION_REQUIRED")
            verify_installed_target(root, args.target_version, args.port)
        return 0
    except BaseException:
        return 1


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    secure_action = _secure_msi_action_main(values)
    if secure_action is not None:
        return secure_action
    return legacy.main(values)


if __name__ == "__main__":
    raise SystemExit(main())
