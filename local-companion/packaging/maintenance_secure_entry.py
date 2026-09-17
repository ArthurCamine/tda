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


# All update/uninstall flows inside the audited maintenance implementation call the
# module-global prepare_uninstall symbol. Replace that symbol before dispatching
# any CLI action so no production path can reach the legacy token-based shutdown.
legacy.prepare_uninstall = prepare_uninstall


def main(argv: list[str] | None = None) -> int:
    return legacy.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
