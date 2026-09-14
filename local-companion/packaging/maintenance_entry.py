from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import winreg
from ctypes import wintypes
from pathlib import Path

PRODUCTION_ORIGIN = "https://dnd.faysk.dev"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "TDA Companion Agent"
PRODUCT_KEY = r"Software\Faysk\TDA Companion"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
ERROR_INVALID_PARAMETER = 87
MAINTENANCE_SCHEMA_VERSION = 1
_OPERATION_ID = re.compile(r"^[0-9a-f]{32}$")


class MaintenanceError(RuntimeError):
    def __init__(self, code: str, *, msi_exit_code: int | None = None):
        super().__init__(code)
        self.code = code
        self.msi_exit_code = msi_exit_code


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def local_root() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise MaintenanceError("LOCALAPPDATA_NOT_FOUND")
    return Path(value).resolve() / "TDA"


def _maintenance_root(root: Path) -> Path:
    return root / "Cache" / "maintenance"


def _operation_path(root: Path, operation_id: str) -> Path:
    return _maintenance_root(root) / "operations" / f"{operation_id}.json"


def _msi_log_path(root: Path, operation_id: str) -> Path:
    return _maintenance_root(root) / "logs" / f"{operation_id}.msi.log"


def _normalize_operation_id(value: str | None) -> str:
    candidate = value or uuid.uuid4().hex
    if not _OPERATION_ID.fullmatch(candidate):
        raise MaintenanceError("MAINTENANCE_OPERATION_ID_INVALID")
    return candidate


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sanitized_error_code(exc: BaseException) -> str:
    if isinstance(exc, MaintenanceError):
        return exc.code
    text = str(exc).strip()
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", text):
        return text
    return type(exc).__name__.upper()


class MaintenanceJournal:
    def __init__(
        self,
        root: Path,
        operation_id: str,
        action: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if action not in {"update", "uninstall"}:
            raise MaintenanceError("MAINTENANCE_ACTION_INVALID")
        self.root = root
        self.operation_id = _normalize_operation_id(operation_id)
        self.path = _operation_path(root, self.operation_id)
        now = time.time()
        self.value: dict[str, object] = {
            "schema_version": MAINTENANCE_SCHEMA_VERSION,
            "operation_id": self.operation_id,
            "action": action,
            "status": "running",
            "stage": "accepted",
            "created_at": now,
            "updated_at": now,
            "error_code": None,
            "failure_stage": None,
            "msi_exit_code": None,
            "msi_log": str(Path("Cache") / "maintenance" / "logs" / f"{self.operation_id}.msi.log"),
        }
        if metadata:
            self.value.update(metadata)
        self._persist()

    def _persist(self) -> None:
        _atomic_json(self.path, self.value)
        _atomic_json(_maintenance_root(self.root) / "last-operation.json", self.value)

    def stage(self, stage: str, **fields: object) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,80}", stage):
            raise MaintenanceError("MAINTENANCE_STAGE_INVALID")
        self.value.update(fields)
        self.value["status"] = "running"
        self.value["stage"] = stage
        self.value["updated_at"] = time.time()
        self._persist()

    def complete(self, **fields: object) -> None:
        self.value.update(fields)
        self.value["status"] = "completed"
        self.value["stage"] = "completed"
        self.value["error_code"] = None
        self.value["failure_stage"] = None
        self.value["updated_at"] = time.time()
        self._persist()

    def fail(self, exc: BaseException) -> None:
        failed_at = str(self.value.get("stage") or "accepted")
        self.value["status"] = "failed"
        self.value["stage"] = "failed"
        self.value["failure_stage"] = failed_at
        self.value["error_code"] = _sanitized_error_code(exc)
        if isinstance(exc, MaintenanceError) and exc.msi_exit_code is not None:
            self.value["msi_exit_code"] = exc.msi_exit_code
        self.value["updated_at"] = time.time()
        self._persist()


def _token(root: Path) -> str | None:
    for path in (
        root / "State" / "pairing-token.txt",
        root / "Companion" / "pairing-token.txt",
    ):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if len(value) >= 43:
            return value
    return None


def _loopback_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _agent_post(root: Path, port: int, *, force: bool) -> bool:
    token = _token(root)
    if not token:
        return False
    payload = json.dumps({"action": "shutdown", "force": force}, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/agent/control",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": PRODUCTION_ORIGIN,
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
    )
    try:
        with _loopback_opener().open(request, timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        return False


def _health(port: int) -> bool:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/health",
        headers={"Cache-Control": "no-store"},
    )
    try:
        with _loopback_opener().open(request, timeout=0.4) as response:
            return response.status == 200
    except Exception:
        return False


def _wait_agent_down(port: int, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _health(port):
            return True
        time.sleep(0.15)
    return not _health(port)


def _remove_startup_value() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


def _process_image(pid: int) -> Path | None:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        length = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(length.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            return None
        return Path(buffer.value).resolve()
    finally:
        kernel32.CloseHandle(handle)


def _installed_companion_pids(root: Path) -> list[int]:
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return []
    versions = (root / "Companion" / "versions").resolve()
    prefix = str(versions).casefold() + os.sep.casefold()
    result: list[int] = []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.casefold() == "tdacompanion.exe":
                image = _process_image(int(entry.th32ProcessID))
                if image is not None and str(image).casefold().startswith(prefix):
                    result.append(int(entry.th32ProcessID))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def _terminate_pid(pid: int) -> None:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not handle:
        return
    try:
        kernel32.TerminateProcess(handle, 0)
        kernel32.WaitForSingleObject(handle, 3000)
    finally:
        kernel32.CloseHandle(handle)


def prepare_uninstall(root: Path, port: int = 8765) -> None:
    _remove_startup_value()
    if _health(port):
        _agent_post(root, port, force=True)
        _wait_agent_down(port, timeout=8)
    for pid in _installed_companion_pids(root):
        if pid != os.getpid():
            _terminate_pid(pid)


def _wait_parent(pid: int | None, timeout: float = 30.0) -> None:
    if not pid:
        return
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        error = int(kernel32.GetLastError())
        if error == ERROR_INVALID_PARAMETER:
            return
        raise MaintenanceError("PARENT_WAIT_FAILED")
    try:
        milliseconds = max(0, int(timeout * 1000))
        result = int(kernel32.WaitForSingleObject(handle, milliseconds))
        if result == WAIT_OBJECT_0:
            return
        if result == WAIT_TIMEOUT:
            raise MaintenanceError("PARENT_EXIT_TIMEOUT")
        raise MaintenanceError("PARENT_WAIT_FAILED")
    finally:
        kernel32.CloseHandle(handle)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_msiexec(arguments: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "msiexec.exe",
        *arguments,
        "/norestart",
        "/L*v",
        str(log_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise MaintenanceError("MSI_TIMEOUT") from exc
    code = int(completed.returncode)
    if code not in (0, 3010):
        raise MaintenanceError("MSI_FAILED", msi_exit_code=code)
    return code


def _write_receipt(root: Path, name: str, value: dict[str, object]) -> None:
    _atomic_json(_maintenance_root(root) / name, value)


def install_update(
    root: Path,
    msi: Path,
    expected_sha256: str,
    expected_version: str,
    parent_pid: int | None,
    port: int,
    operation_id: str | None = None,
) -> None:
    operation_id = _normalize_operation_id(operation_id)
    journal = MaintenanceJournal(
        root,
        operation_id,
        "update",
        metadata={
            "target_version": expected_version,
            "expected_sha256": expected_sha256.casefold(),
        },
    )
    log_path = _msi_log_path(root, operation_id)
    try:
        journal.stage("waiting_for_ui_exit")
        _wait_parent(parent_pid)

        journal.stage("verifying_asset")
        if not msi.is_file() or _sha256(msi).casefold() != expected_sha256.casefold():
            raise MaintenanceError("UPDATE_HASH_MISMATCH")

        journal.stage("stopping_agent")
        prepare_uninstall(root, port)

        journal.stage("running_msi")
        msi_exit_code = _run_msiexec(["/i", str(msi), "/passive"], log_path)
        journal.stage("verifying_install", msi_exit_code=msi_exit_code)

        marker = root / "Companion" / "current-version.txt"
        installed = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        if installed != expected_version:
            raise MaintenanceError("UPDATE_VERSION_MISMATCH")
        executable = root / "Companion" / "versions" / expected_version / "TDACompanion.exe"
        if not executable.is_file():
            raise MaintenanceError("UPDATED_EXECUTABLE_MISSING")

        journal.stage("restarting_agent")
        subprocess.Popen(
            [str(executable), "--agent", "--startup"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            ),
        )
        journal.stage("restarting_ui")
        subprocess.Popen([str(executable), "--ui"], close_fds=True)

        journal.complete(msi_exit_code=msi_exit_code, installed_version=expected_version)
        _write_receipt(
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
    except BaseException as exc:
        journal.fail(exc)
        raise


def _product_code() -> str:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PRODUCT_KEY, 0, winreg.KEY_READ) as key:
        value, _kind = winreg.QueryValueEx(key, "ProductCode")
    text = str(value).strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise MaintenanceError("PRODUCT_CODE_INVALID")
    return text


def _purge_user_data(root: Path) -> None:
    for name in ("State", "Data", "Logs", "Models", "Runtime", "Cache"):
        shutil.rmtree(root / name, ignore_errors=True)
    # MSI owns Companion. Remove it only after msiexec completed and only if it
    # still contains generated leftovers rather than another installed version.
    companion = root / "Companion"
    if companion.exists():
        shutil.rmtree(companion, ignore_errors=True)
    try:
        root.rmdir()
    except OSError:
        pass
    if root.exists():
        raise MaintenanceError("PURGE_INCOMPLETE")


def uninstall(
    root: Path,
    *,
    purge: bool,
    parent_pid: int | None,
    port: int,
    operation_id: str | None = None,
) -> None:
    operation_id = _normalize_operation_id(operation_id)
    journal = MaintenanceJournal(
        root,
        operation_id,
        "uninstall",
        metadata={"purge": bool(purge)},
    )
    log_path = _msi_log_path(root, operation_id)
    try:
        journal.stage("waiting_for_ui_exit")
        _wait_parent(parent_pid)

        journal.stage("resolving_product")
        product_code = _product_code()

        journal.stage("stopping_agent")
        prepare_uninstall(root, port)

        journal.stage("running_msi")
        msi_exit_code = _run_msiexec(["/x", product_code, "/passive"], log_path)
        if purge:
            # Full purge intentionally removes its own Cache/maintenance evidence.
            # If purge fails, the exception handler recreates a sanitized failed
            # operation receipt so the user has something actionable to inspect.
            journal.stage("purging_data", msi_exit_code=msi_exit_code)
            _purge_user_data(root)
            return

        journal.complete(msi_exit_code=msi_exit_code)
        _write_receipt(
            root,
            "last-uninstall.json",
            {
                "operation_id": operation_id,
                "status": "uninstalled",
                "purge": False,
                "msi_exit_code": msi_exit_code,
                "msi_log": str(Path("Cache") / "maintenance" / "logs" / f"{operation_id}.msi.log"),
                "at": time.time(),
            },
        )
    except BaseException as exc:
        journal.fail(exc)
        raise


def _schedule_self_cleanup(operation_id: str) -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    executable = Path(sys.executable).resolve()
    staging = executable.parent
    if (
        staging.name != operation_id
        or staging.parent.name != "TDACompanionMaintenance"
        or executable.name.casefold() != "tdacompanionmaintenance.exe"
    ):
        return
    path_b64 = base64.b64encode(str(staging).encode("utf-8")).decode("ascii")
    script = (
        "$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
        + path_b64
        + "')); Start-Sleep -Milliseconds 900; "
        "Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="TDACompanionMaintenance")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--prepare-uninstall", action="store_true")
    actions.add_argument("--install-update", action="store_true")
    actions.add_argument("--uninstall", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--operation-id")
    parser.add_argument("--cleanup-self", action="store_true")
    parser.add_argument("--msi", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--version")
    parser.add_argument("--purge", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = (args.root or local_root()).resolve()
    operation_id: str | None = None
    try:
        operation_id = _normalize_operation_id(args.operation_id) if not args.prepare_uninstall else None
        if args.prepare_uninstall:
            prepare_uninstall(root, args.port)
        elif args.install_update:
            if args.msi is None or not args.sha256 or not args.version:
                raise MaintenanceError("UPDATE_ARGUMENTS_REQUIRED")
            install_update(
                root,
                args.msi.resolve(),
                args.sha256,
                args.version,
                args.parent_pid,
                args.port,
                operation_id,
            )
        else:
            uninstall(
                root,
                purge=bool(args.purge),
                parent_pid=args.parent_pid,
                port=args.port,
                operation_id=operation_id,
            )
        return 0
    except BaseException as exc:
        try:
            _write_receipt(
                root,
                "last-maintenance-error.json",
                {
                    "operation_id": operation_id,
                    "error_code": _sanitized_error_code(exc),
                    "error_type": type(exc).__name__,
                    "at": time.time(),
                },
            )
        except Exception:
            pass
        return 1
    finally:
        if args.cleanup_self and operation_id is not None:
            try:
                _schedule_self_cleanup(operation_id)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
