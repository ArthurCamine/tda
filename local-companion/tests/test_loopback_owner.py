from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tda_companion.loopback_owner import LoopbackOwnerError, verify_loopback_owner


def _listener(pid: int, *, port: int = 8765, host: str = "127.0.0.1"):
    return SimpleNamespace(
        status="LISTEN",
        laddr=SimpleNamespace(ip=host, port=port),
        pid=pid,
    )


def test_loopback_owner_requires_reported_pid_to_own_exact_listener(tmp_path: Path):
    executable = tmp_path / "TDACompanion.exe"
    executable.write_bytes(b"companion")

    verify_loopback_owner(
        8765,
        4321,
        executable,
        connection_reader=lambda: [_listener(4321)],
        process_executable=lambda pid: str(executable) if pid == 4321 else "",
    )


def test_loopback_owner_rejects_health_pid_that_does_not_own_port(tmp_path: Path):
    executable = tmp_path / "TDACompanion.exe"
    executable.write_bytes(b"companion")

    with pytest.raises(LoopbackOwnerError, match="AGENT_PORT_OWNER_MISMATCH"):
        verify_loopback_owner(
            8765,
            4321,
            executable,
            connection_reader=lambda: [_listener(9999)],
            process_executable=lambda _pid: str(executable),
        )


def test_loopback_owner_rejects_ambiguous_listener_ownership(tmp_path: Path):
    executable = tmp_path / "TDACompanion.exe"
    executable.write_bytes(b"companion")

    with pytest.raises(LoopbackOwnerError, match="AGENT_PORT_OWNER_MISMATCH"):
        verify_loopback_owner(
            8765,
            4321,
            executable,
            connection_reader=lambda: [_listener(4321), _listener(9999)],
            process_executable=lambda _pid: str(executable),
        )


def test_loopback_owner_rejects_other_executable_even_with_correct_pid(tmp_path: Path):
    expected = tmp_path / "TDACompanion.exe"
    foreign = tmp_path / "Foreign.exe"
    expected.write_bytes(b"companion")
    foreign.write_bytes(b"foreign")

    with pytest.raises(LoopbackOwnerError, match="AGENT_PROCESS_EXECUTABLE_MISMATCH"):
        verify_loopback_owner(
            8765,
            4321,
            expected,
            connection_reader=lambda: [_listener(4321)],
            process_executable=lambda _pid: str(foreign),
        )


def test_loopback_owner_ignores_non_loopback_and_other_ports(tmp_path: Path):
    executable = tmp_path / "TDACompanion.exe"
    executable.write_bytes(b"companion")

    with pytest.raises(LoopbackOwnerError, match="AGENT_PORT_OWNER_MISMATCH"):
        verify_loopback_owner(
            8765,
            4321,
            executable,
            connection_reader=lambda: [
                _listener(4321, host="0.0.0.0"),
                _listener(4321, port=9999),
            ],
            process_executable=lambda _pid: str(executable),
        )
