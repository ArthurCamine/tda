from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from pathlib import Path

import maintenance_entry as legacy


def _scan_tda_processes(root: Path) -> tuple[list[int], list[int]]:
    """Return installed Companion PIDs and same-name PIDs whose image is unreadable.

    A process named TDACompanion.exe with an image path below Companion/versions
    is safe for maintenance to terminate. A same-name process whose image cannot
    be queried is deliberately *not* killed, but it is also not ignored: update
    and uninstall fail closed instead of deleting files while ownership is
    ambiguous.
    """
    if os.name != "nt":
        return legacy._installed_companion_pids(root), []

    kernel32 = legacy.ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(legacy.TH32CS_SNAPPROCESS, 0)
    if snapshot == legacy.INVALID_HANDLE_VALUE:
        raise legacy.MaintenanceError("TDA_PROCESS_SCAN_FAILED")

    versions = (root / "Companion" / "versions").resolve()
    prefix = (os.path.normcase(str(versions)).rstrip("\\/") + os.sep).casefold()
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
                    else:
                        normalized = os.path.normcase(str(image)).casefold()
                        if normalized.startswith(prefix):
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
    """Stop every installed TDA Companion process and prove postconditions."""
    for attempt in range(4):
        remaining = _other_installed_pids(root)
        if not remaining:
            break
        for pid in remaining:
            legacy._terminate_pid(pid)
        time.sleep(0.2 * (attempt + 1))

    if _other_installed_pids(root):
        raise legacy.MaintenanceError("TDA_PROCESS_STILL_RUNNING")
    if require_port_free:
        if port is None:
            raise legacy.MaintenanceError("AGENT_PORT_REQUIRED")
        _wait_port_free(port)


def prepare_major_upgrade(root: Path, port: int = 8765) -> None:
    """Prepare an MSI MajorUpgrade without mutating MSI-owned registration.

    The helper embedded in the *new* MSI exists specifically to stop processes
    from an older installed Companion before RemoveExistingProducts. Registry,
    Startup and shortcuts remain exclusively MSI-owned so rollback can restore
    them transactionally. The Agent port must also be free before installation
    is allowed to continue; a foreign listener therefore aborts the upgrade.
    """
    _stop_installed_processes(root, port=port, require_port_free=True)


def prepare_uninstall(root: Path, port: int = 8765) -> None:
    """Stop installed Companion processes before an explicit uninstall.

    Maintenance deliberately does not read or transmit the pairing token and it
    does not mutate MSI-owned Startup/Registry state. An unrelated listener on
    the Agent port does not prevent explicit uninstall, but ambiguous same-name
    process ownership does fail closed.
    """
    del port
    _stop_installed_processes(root)


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


def _wait_for_target_agent(
    executable: Path,
    expected_version: str,
    port: int,
    process,
    *,
    timeout: float = 12.0,
) -> None:
    deadline = time.monotonic() + timeout
    expected_image = os.path.normcase(str(executable.resolve())).casefold()

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise legacy.MaintenanceError("UPDATED_AGENT_EXITED")

        health = _target_health(port)
        if health is not None:
            pid = health.get("pid")
            image = legacy._process_image(int(pid)) if isinstance(pid, int) and pid > 0 else None
            image_matches = (
                image is not None
                and os.path.normcase(str(image)).casefold() == expected_image
            )
            if (
                health.get("product_id") == "tda-companion"
                and str(health.get("api_version") or "") == "1"
                and health.get("service_version") == expected_version
                and health.get("port") == port
                and pid == getattr(process, "pid", None)
                and image_matches
            ):
                return
        time.sleep(0.15)

    raise legacy.MaintenanceError("UPDATED_AGENT_NOT_READY")


def install_update(
    root: Path,
    msi: Path,
    expected_sha256: str,
    expected_version: str,
    parent_pid: int | None,
    port: int,
    operation_id: str | None = None,
) -> None:
    """Install one target version and prove that version is actually running."""
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

        journal.stage("stopping_agent")
        # Keep Registry/Startup MSI-owned. The new MSI will mutate them inside its
        # transaction; if installation fails the previous registration survives.
        _stop_installed_processes(root, port=port, require_port_free=True)

        journal.stage("running_msi")
        msi_exit_code = legacy._run_msiexec(["/i", str(msi), "/passive"], log_path)
        journal.stage("verifying_install", msi_exit_code=msi_exit_code)

        marker = root / "Companion" / "current-version.txt"
        installed = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        if installed != expected_version:
            raise legacy.MaintenanceError("UPDATE_VERSION_MISMATCH")
        executable = root / "Companion" / "versions" / expected_version / "TDACompanion.exe"
        if not executable.is_file():
            raise legacy.MaintenanceError("UPDATED_EXECUTABLE_MISSING")

        journal.stage("restarting_agent")
        agent_process = legacy.subprocess.Popen(
            [str(executable), "--agent", "--startup"],
            stdin=legacy.subprocess.DEVNULL,
            stdout=legacy.subprocess.DEVNULL,
            stderr=legacy.subprocess.DEVNULL,
            close_fds=True,
            creationflags=(
                getattr(legacy.subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(legacy.subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            ),
        )

        journal.stage("verifying_agent")
        _wait_for_target_agent(executable, expected_version, port, agent_process)

        journal.stage("restarting_ui")
        legacy.subprocess.Popen([str(executable), "--ui"], close_fds=True)

        journal.complete(msi_exit_code=msi_exit_code, installed_version=expected_version)
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
    except BaseException as exc:
        journal.fail(exc)
        raise


# All update/uninstall flows inside the audited maintenance implementation call
# module-global symbols. Replace both before dispatching so production never uses
# the legacy token-based shutdown or marks an update complete before exact target
# health has been observed.
legacy.prepare_uninstall = prepare_uninstall
legacy.install_update = install_update


def _prepare_major_upgrade_main(argv: list[str]) -> int | None:
    if "--prepare-major-upgrade" not in argv:
        return None
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--prepare-major-upgrade", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    try:
        args = parser.parse_args(argv)
        root = (args.root or legacy.local_root()).resolve()
        prepare_major_upgrade(root, args.port)
        return 0
    except BaseException:
        return 1


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    major_upgrade = _prepare_major_upgrade_main(values)
    if major_upgrade is not None:
        return major_upgrade
    return legacy.main(values)


if __name__ == "__main__":
    raise SystemExit(main())
