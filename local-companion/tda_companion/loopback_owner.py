from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable

_VERSION_DIR = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_COMPANION_EXE = "tdacompanion.exe"


class LoopbackOwnerError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _resolved_path(path: str | Path) -> Path:
    try:
        return Path(path).resolve(strict=True)
    except OSError as exc:
        raise LoopbackOwnerError("AGENT_PROCESS_EXECUTABLE_UNVERIFIED") from exc


def _normalized_path(path: Path) -> str:
    return os.path.normcase(str(path))


def _trusted_companion_executable(actual_value: str | Path, expected_value: str | Path) -> bool:
    expected = _resolved_path(expected_value)
    actual = _resolved_path(actual_value)
    if _normalized_path(actual) == _normalized_path(expected):
        return True

    if expected.name.casefold() != _COMPANION_EXE:
        return False
    versions_root = expected.parent.parent
    if (
        versions_root.name.casefold() != "versions"
        or _VERSION_DIR.fullmatch(expected.parent.name) is None
    ):
        return False
    try:
        relative = actual.relative_to(versions_root)
    except ValueError:
        return False
    return (
        len(relative.parts) == 2
        and _VERSION_DIR.fullmatch(relative.parts[0]) is not None
        and relative.parts[1].casefold() == _COMPANION_EXE
    )


def _listener_pids(port: int, connections: Iterable[Any]) -> set[int]:
    result: set[int] = set()
    for connection in connections:
        try:
            status = str(connection.status or "")
            address = connection.laddr
            host = str(getattr(address, "ip", address[0] if address else ""))
            local_port = int(getattr(address, "port", address[1] if address else 0))
            pid = connection.pid
        except (AttributeError, IndexError, TypeError, ValueError):
            continue
        if (
            status.upper() == "LISTEN"
            and host == "127.0.0.1"
            and local_port == port
            and isinstance(pid, int)
            and pid > 0
        ):
            result.add(pid)
    return result


def verify_loopback_owner(
    port: int,
    reported_pid: int,
    expected_executable: Path,
    *,
    connection_reader: Callable[[], Iterable[Any]] | None = None,
    process_executable: Callable[[int], str] | None = None,
) -> None:
    """Fail closed unless the reported Agent PID owns the IPv4 loopback listener
    and runs a trusted Companion executable.

    The current executable is always accepted. Installed builds also accept a
    sibling semver TDACompanion.exe under the same Companion/versions root so the
    existing read-only version-compatibility path keeps working during upgrades.

    This is defense in depth against a different local process spoofing /health.
    It is not a privilege boundary against arbitrary code already running as the
    same Windows user, which can also modify per-user installation files.
    """
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise LoopbackOwnerError("AGENT_PORT_OWNER_UNVERIFIED")
    if not isinstance(reported_pid, int) or reported_pid <= 0:
        raise LoopbackOwnerError("AGENT_PORT_OWNER_UNVERIFIED")

    if connection_reader is None or process_executable is None:
        try:
            import psutil
        except ImportError as exc:
            raise LoopbackOwnerError("AGENT_PORT_OWNER_UNVERIFIED") from exc
        if connection_reader is None:
            connection_reader = lambda: psutil.net_connections(kind="tcp")
        if process_executable is None:
            process_executable = lambda pid: psutil.Process(pid).exe()

    try:
        owners = _listener_pids(port, connection_reader())
    except BaseException as exc:
        raise LoopbackOwnerError("AGENT_PORT_OWNER_UNVERIFIED") from exc
    if owners != {reported_pid}:
        raise LoopbackOwnerError("AGENT_PORT_OWNER_MISMATCH")

    try:
        actual_raw = process_executable(reported_pid)
    except BaseException as exc:
        raise LoopbackOwnerError("AGENT_PROCESS_EXECUTABLE_UNVERIFIED") from exc
    if not _trusted_companion_executable(actual_raw, expected_executable):
        raise LoopbackOwnerError("AGENT_PROCESS_EXECUTABLE_MISMATCH")
