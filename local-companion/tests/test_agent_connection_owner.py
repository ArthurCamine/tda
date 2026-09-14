from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tda_companion import VERSION
import tda_companion.agent_connection as agent_connection_module
from tda_companion.agent_connection import AgentConnection, AgentConnectionError
from tda_companion.loopback_owner import LoopbackOwnerError


TOKEN = "t" * 43


class _Response:
    def __init__(self, value: object, status: int = 200):
        self.status = status
        self._raw = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size: int = -1) -> bytes:
        return self._raw


class _RecordingOpener:
    def __init__(self):
        self.requests: list[Any] = []

    def open(self, request, timeout=0):
        self.requests.append(request)
        if request.full_url.endswith("/api/v1/health"):
            return _Response(
                {
                    "product_id": "tda-companion",
                    "api_version": "1",
                    "service_version": VERSION,
                    "pid": 4321,
                    "port": 8765,
                    "lifecycle": "ready",
                }
            )
        return _Response({"ok": True})


def _authorization(request) -> str | None:
    return request.get_header("Authorization")


def test_spoofed_health_cannot_receive_bearer_when_port_owner_mismatches(tmp_path: Path):
    executable = tmp_path / "TDACompanion.exe"
    executable.write_bytes(b"companion")
    opener = _RecordingOpener()

    def reject_owner(_port: int, _pid: int, _executable: Path) -> None:
        raise LoopbackOwnerError("AGENT_PORT_OWNER_MISMATCH")

    connection = AgentConnection(
        TOKEN,
        8765,
        lambda: None,
        expected_executable=executable,
        owner_verifier=reject_owner,
        opener=opener,
    )

    with pytest.raises(AgentConnectionError, match="AGENT_PORT_CONFLICT"):
        connection.get("/system")

    assert len(opener.requests) == 1
    assert opener.requests[0].full_url.endswith("/api/v1/health")
    assert _authorization(opener.requests[0]) is None
    assert connection.status()["state"] == "port_conflict"
    assert connection.status()["error"] == "AGENT_PORT_OWNER_MISMATCH"


def test_verified_owner_allows_authenticated_request(tmp_path: Path):
    executable = tmp_path / "TDACompanion.exe"
    executable.write_bytes(b"companion")
    opener = _RecordingOpener()
    verified: list[tuple[int, int, Path]] = []

    def accept_owner(port: int, pid: int, expected: Path) -> None:
        verified.append((port, pid, expected))

    connection = AgentConnection(
        TOKEN,
        8765,
        lambda: None,
        expected_executable=executable,
        owner_verifier=accept_owner,
        opener=opener,
    )

    assert connection.get("/system") == {"ok": True}
    assert verified == [(8765, 4321, executable)]
    assert len(opener.requests) == 2
    assert _authorization(opener.requests[0]) is None
    assert _authorization(opener.requests[1]) == f"Bearer {TOKEN}"


def test_frozen_desktop_enables_owner_verification_without_explicit_path(tmp_path: Path, monkeypatch):
    executable = tmp_path / "TDACompanion.exe"
    executable.write_bytes(b"companion")
    opener = _RecordingOpener()
    verified: list[tuple[int, int, Path]] = []

    monkeypatch.setattr(agent_connection_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(agent_connection_module.sys, "executable", str(executable))

    def accept_owner(port: int, pid: int, expected: Path) -> None:
        verified.append((port, pid, expected))

    connection = AgentConnection(
        TOKEN,
        8765,
        lambda: None,
        owner_verifier=accept_owner,
        opener=opener,
    )

    assert connection.get("/system") == {"ok": True}
    assert verified == [(8765, 4321, executable)]
    assert connection.expected_executable == executable
