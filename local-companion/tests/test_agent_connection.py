from __future__ import annotations

from typing import Any

import pytest

from tda_companion.agent_connection import (
    AgentConnection,
    AgentConnectionError,
    AgentProbe,
    AgentTransportError,
)


TOKEN = "t" * 43


def _payload(version: str = "0.3.2") -> dict[str, Any]:
    return {
        "product_id": "tda-companion",
        "api_version": "1",
        "service_version": version,
        "pid": 4321,
        "port": 8765,
        "lifecycle": "ready",
    }


def test_connection_recovers_once_before_retrying_request(monkeypatch):
    starts = 0

    def start_agent():
        nonlocal starts
        starts += 1

    connection = AgentConnection(TOKEN, 8765, start_agent, expected_version="0.3.2")

    def fake_probe(*, timeout=0.5):
        if starts:
            probe = AgentProbe("exact", _payload())
        else:
            probe = AgentProbe("unavailable", code="AGENT_CONNECTION_REFUSED")
        connection._record_probe(probe)
        return probe

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(connection, "probe", fake_probe)
    monkeypatch.setattr(
        connection,
        "_request_once",
        lambda method, path, body=None, idempotency_key=None: calls.append((method, path)) or {"ok": True},
    )

    assert connection.get("/jobs") == {"ok": True}
    assert starts == 1
    assert calls == [("GET", "/jobs")]
    assert connection.status()["state"] == "ready"


def test_retry_reuses_same_idempotency_key_after_transport_failure(monkeypatch):
    connection = AgentConnection(TOKEN, 8765, lambda: None, expected_version="0.3.2")

    def exact_probe(**_kwargs):
        probe = AgentProbe("exact", _payload())
        connection._record_probe(probe)
        return probe

    calls: list[str | None] = []

    def request_once(_method, _path, _body=None, *, idempotency_key=None):
        calls.append(idempotency_key)
        if len(calls) == 1:
            raise AgentTransportError("AGENT_CONNECTION_REFUSED")
        return {"ok": True}

    monkeypatch.setattr(connection, "probe", exact_probe)
    monkeypatch.setattr(connection, "_request_once", request_once)

    assert connection.post("/jobs", {"kind": "fixture"}, idempotency_key="job-fixed-key") == {"ok": True}
    assert calls == ["job-fixed-key", "job-fixed-key"]


def test_manual_stop_disables_automatic_recovery(monkeypatch):
    starts = 0

    def start_agent():
        nonlocal starts
        starts += 1

    connection = AgentConnection(TOKEN, 8765, start_agent)
    connection.mark_stopped_by_user()
    monkeypatch.setattr(
        connection,
        "probe",
        lambda **_kwargs: pytest.fail("probe must not run after explicit stop"),
    )

    with pytest.raises(AgentConnectionError, match="AGENT_STOPPED_BY_USER"):
        connection.get("/jobs")
    assert starts == 0
    assert connection.status()["state"] == "stopped_by_user"


def test_foreign_listener_blocks_before_bearer_request(monkeypatch):
    connection = AgentConnection(TOKEN, 8765, lambda: None)

    def foreign_probe(**_kwargs):
        probe = AgentProbe("foreign", {"hello": "world"}, "AGENT_IDENTITY_MISMATCH")
        connection._record_probe(probe)
        return probe

    monkeypatch.setattr(connection, "probe", foreign_probe)
    monkeypatch.setattr(
        connection,
        "_request_once",
        lambda *_args, **_kwargs: pytest.fail("authenticated request must not reach foreign listener"),
    )

    with pytest.raises(AgentConnectionError, match="AGENT_PORT_CONFLICT"):
        connection.get("/system")
    assert connection.status()["state"] == "port_conflict"


def test_failed_recovery_enters_backoff_instead_of_spawn_storm(monkeypatch):
    starts = 0

    def start_agent():
        nonlocal starts
        starts += 1
        raise OSError("spawn failed")

    connection = AgentConnection(TOKEN, 8765, start_agent)

    def unavailable_probe(**_kwargs):
        probe = AgentProbe("unavailable", code="AGENT_CONNECTION_REFUSED")
        connection._record_probe(probe)
        return probe

    monkeypatch.setattr(connection, "probe", unavailable_probe)

    with pytest.raises(AgentConnectionError, match="AGENT_START_FAILED"):
        connection.get("/jobs")
    with pytest.raises(AgentConnectionError, match="AGENT_RECONNECT_BACKOFF"):
        connection.get("/jobs")

    assert starts == 1
    assert connection.status()["retry_after_seconds"] > 0


def test_compatible_agent_is_read_only_until_exact_version(monkeypatch):
    connection = AgentConnection(TOKEN, 8765, lambda: None, expected_version="0.3.3")
    compatible = AgentProbe("compatible", _payload("0.3.2"), "AGENT_VERSION_MISMATCH")

    def compatible_probe(**_kwargs):
        connection._record_probe(compatible)
        return compatible

    monkeypatch.setattr(connection, "probe", compatible_probe)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        connection,
        "_request_once",
        lambda method, path, body=None, idempotency_key=None: calls.append((method, path)) or {"ok": True},
    )

    assert connection.get("/jobs") == {"ok": True}
    with pytest.raises(AgentConnectionError, match="AGENT_VERSION_MISMATCH"):
        connection.post("/lifecycle", {"action": "pause"})
    assert connection.post("/agent/control", {"action": "shutdown"}) == {"ok": True}
    assert calls == [("GET", "/jobs"), ("POST", "/agent/control")]


def test_shutdown_is_idempotent_when_agent_is_already_down(monkeypatch):
    connection = AgentConnection(TOKEN, 8765, lambda: None)

    def unavailable_probe(**_kwargs):
        probe = AgentProbe("unavailable", code="AGENT_CONNECTION_REFUSED")
        connection._record_probe(probe)
        return probe

    monkeypatch.setattr(connection, "probe", unavailable_probe)

    assert connection.stop_by_user() == {"accepted": False, "already_stopped": True}
    assert connection.status()["state"] == "stopped_by_user"
