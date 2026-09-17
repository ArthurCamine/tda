from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Iterable


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
    # Authentication is stricter than recovery identity. Only the exact
    # executable expected by this desktop may receive the pairing token. Old
    # sibling versions are handled by Single Active Version reconciliation and
    # are never an authenticated read-only fallback.
    expected = _resolved_path(expected_value)
    actual = _resolved_path(actual_value)
    return _normalized_path(actual) == _normalized_path(expected)


def _listener_address(address: Any) -> tuple[str, int]:
    if address is None:
        raise ValueError("listener address missing")
    if hasattr(address, "ip") and hasattr(address, "port"):
        return str(address.ip), int(address.port)
    if len(address) >= 2:
        return str(address[0]), int(address[1])
    raise ValueError("listener address invalid")


def _listener_pids(port: int, connections: Iterable[Any]) -> set[int]:
    result: set[int] = set()
    for connection in connections:
        try:
            status = str(connection.status or "")
            host, local_port = _listener_address(connection.laddr)
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
    """Fail closed unless the reported Agent is the exact packaged target.

    This verification is used before authenticated loopback requests. Recovery
    of stale installed processes is intentionally a separate mechanism that can
    recognize an old TDA process even when its executable has already disappeared
    from disk; that weaker recovery identity is never enough to receive a token.
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
