from __future__ import annotations

import os
import socket
import sys
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


def test_loopback_owner_accepts_sibling_installed_version_for_read_only_compatibility(tmp_path: Path):
    versions = tmp_path / "TDA" / "Companion" / "versions"
    expected = versions / "0.3.4" / "TDACompanion.exe"
    compatible = versions / "0.3.3" / "TDACompanion.exe"
    expected.parent.mkdir(parents=True)
    compatible.parent.mkdir(parents=True)
    expected.write_bytes(b"current")
    compatible.write_bytes(b"previous")

    verify_loopback_owner(
        8765,
        4321,
        expected,
        connection_reader=lambda: [_listener(4321)],
        process_executable=lambda _pid: str(compatible),
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


def test_loopback_owner_rejects_same_named_binary_outside_installed_versions_root(tmp_path: Path):
    versions = tmp_path / "TDA" / "Companion" / "versions"
    expected = versions / "0.3.4" / "TDACompanion.exe"
    foreign = tmp_path / "attacker" / "TDACompanion.exe"
    expected.parent.mkdir(parents=True)
    foreign.parent.mkdir(parents=True)
    expected.write_bytes(b"current")
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


@pytest.mark.skipif(os.name != "nt", reason="real listener ownership uses Windows process tables")
def test_windows_real_listener_resolves_to_current_process_without_mocking_psutil():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = int(listener.getsockname()[1])

        verify_loopback_owner(
            port,
            os.getpid(),
            Path(sys.executable),
        )
