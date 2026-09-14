from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Iterable


class LoopbackOwnerError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _normalized_path(path: str | Path) -> str:
    try:
        return os.path.normcase(str(Path(path).resolve(strict=True)))
    except OSError as exc:
        raise LoopbackOwnerError("AGENT_PROCESS_EXECUTABLE_UNVERIFIED") from exc


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
    and that process is running the exact Companion executable expected by the
    desktop process.

    This is defense in depth against a different local process spoofing /health.
    It is not a privilege boundary against arbitrary code already running as the
    same Windows user.
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

    expected = _normalized_path(expected_executable)
    try:
        actual_raw = process_executable(reported_pid)
    except BaseException as exc:
        raise LoopbackOwnerError("AGENT_PROCESS_EXECUTABLE_UNVERIFIED") from exc
    actual = _normalized_path(actual_raw)
    if actual != expected:
        raise LoopbackOwnerError("AGENT_PROCESS_EXECUTABLE_MISMATCH")
