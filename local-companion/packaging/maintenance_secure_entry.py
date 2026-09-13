from __future__ import annotations

import os
from pathlib import Path

import maintenance_entry as legacy


def prepare_uninstall(root: Path, port: int = 8765) -> None:
    """Stop only TDA Companion processes from the installed per-user tree.

    Maintenance deliberately does not read or transmit the pairing token. The
    helper already runs after the UI handoff and can identify the product by the
    executable path under Companion/versions, which avoids authenticating to an
    arbitrary loopback listener during update/uninstall.
    """
    del port  # Maintenance is process/path based; loopback identity is irrelevant here.
    legacy._remove_startup_value()
    for pid in legacy._installed_companion_pids(root):
        if pid != os.getpid():
            legacy._terminate_pid(pid)


# All update/uninstall flows inside the audited maintenance implementation call the
# module-global prepare_uninstall symbol. Replace that symbol before dispatching
# any CLI action so no production path can reach the legacy token-based shutdown.
legacy.prepare_uninstall = prepare_uninstall


def main(argv: list[str] | None = None) -> int:
    return legacy.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
