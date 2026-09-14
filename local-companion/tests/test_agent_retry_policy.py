from __future__ import annotations

from typing import Any

import pytest

from tda_companion.agent_connection import AgentConnection, AgentConnectionError, AgentProbe, AgentTransportError

TOKEN = "t" * 43


def _payload() -> dict[str, Any]:
    return {
        "product_id": "tda-companion",
        "api_version": "1",
        "service_version": "0.3.4",
        "pid": 4321,
        "port": 8765,
        "lifecycle": "ready",
    }


def _exact_connection(monkeypatch) -> AgentConnection:
    connection = AgentConnection(TOKEN, 8765, lambda: None, expected_version="0.3.4")

    def exact_probe(**_kwargs):
        probe = AgentProbe("exact", _payload())
        connection._record_probe(probe)
        return probe

    monkeypatch.setattr(connection, "probe", exact_probe)
    monkeypatch.setattr(connection, "_recover", lambda: None)
    return connection


def test_unkeyed_non_idempotent_post_is_not_replayed_after_transport_failure(monkeypatch):
    connection = _exact_connection(monkeypatch)
    calls = 0

    def request_once(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AgentTransportError("AGENT_CONNECTION_REFUSED")

    monkeypatch.setattr(connection, "_request_once", request_once)

    with pytest.raises(AgentConnectionError, match="AGENT_MUTATION_RESULT_UNCERTAIN"):
        connection.post("/jobs/some-job/action", {"action": "cancel"})
    assert calls == 1


def test_lifecycle_post_can_retry_because_target_state_is_idempotent(monkeypatch):
    connection = _exact_connection(monkeypatch)
    calls = 0

    def request_once(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AgentTransportError("AGENT_CONNECTION_REFUSED")
        return {"paused": True}

    monkeypatch.setattr(connection, "_request_once", request_once)

    assert connection.post("/lifecycle", {"action": "pause"}) == {"paused": True}
    assert calls == 2


def test_keyed_mutation_retries_with_same_key(monkeypatch):
    connection = _exact_connection(monkeypatch)
    seen: list[str | None] = []

    def request_once(_method, _path, _body=None, *, idempotency_key=None):
        seen.append(idempotency_key)
        if len(seen) == 1:
            raise AgentTransportError("AGENT_CONNECTION_REFUSED")
        return {"created": True}

    monkeypatch.setattr(connection, "_request_once", request_once)

    assert connection.post("/jobs", {"kind": "synthetic.fixture"}, idempotency_key="fixed-key") == {"created": True}
    assert seen == ["fixed-key", "fixed-key"]
