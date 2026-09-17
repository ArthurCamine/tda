from __future__ import annotations

import os
import time
from pathlib import Path

import maintenance_entry as legacy


def _other_installed_pids(root: Path) -> list[int]:
    current = os.getpid()
    return [pid for pid in legacy._installed_companion_pids(root) if pid != current]


def prepare_uninstall(root: Path, port: int = 8765) -> None:
    """Stop every installed TDA Companion process and prove it is gone.

    Maintenance deliberately does not read or transmit the pairing token. The
    helper identifies the product by the executable image path under
    Companion/versions, including a still-running image whose file has already
    disappeared from disk. A failed termination is a hard stop: update/uninstall
    must never remove another version while one of its processes is still alive.
    """
    del port  # Process ownership, not loopback authentication, is authoritative here.
    legacy._remove_startup_value()

    for attempt in range(4):
        remaining = _other_installed_pids(root)
        if not remaining:
            return
        for pid in remaining:
            legacy._terminate_pid(pid)
        time.sleep(0.2 * (attempt + 1))

    if _other_installed_pids(root):
        raise legacy.MaintenanceError("TDA_PROCESS_STILL_RUNNING")


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
    """Install one target version and prove that version is actually running.

    The new Agent performs its own Single Active Version reconciliation during
    bootstrap. Therefore reaching exact health here also proves that stale
    installed processes/directories did not prevent the target from becoming the
    operational version. The UI is opened only after this gate passes.
    """
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
        prepare_uninstall(root, port)

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


def main(argv: list[str] | None = None) -> int:
    return legacy.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
