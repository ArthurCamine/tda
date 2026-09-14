from __future__ import annotations

from types import SimpleNamespace

import pytest

from tda_companion.agent_connection import AgentProbe
from tda_companion import windows_app


def _args():
    return SimpleNamespace(
        port=8765,
        state_root=SimpleNamespace(__str__=lambda self: "state"),
        data_root=SimpleNamespace(__str__=lambda self: "data"),
        logs_root=SimpleNamespace(__str__=lambda self: "logs"),
        origins=frozenset({windows_app.PRODUCTION_ORIGIN}),
    )


@pytest.mark.parametrize("state", ["exact", "compatible", "foreign", "incompatible"])
def test_existing_listener_is_never_blindly_replaced(monkeypatch, state: str):
    args = _args()
    monkeypatch.setattr(
        windows_app,
        "probe_agent",
        lambda *_args, **_kwargs: AgentProbe(state, code="observed"),
    )
    monkeypatch.setattr(
        windows_app.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("must not spawn over an occupied/identified port"),
    )

    assert windows_app.ensure_agent_running(args) is None


def test_unavailable_agent_spawns_and_waits_for_exact_version(monkeypatch, tmp_path):
    args = SimpleNamespace(
        port=8765,
        state_root=tmp_path / "State",
        data_root=tmp_path / "Data",
        logs_root=tmp_path / "Logs",
        origins=frozenset({windows_app.PRODUCTION_ORIGIN}),
    )
    process = SimpleNamespace(poll=lambda: None)
    observed = {}

    monkeypatch.setattr(
        windows_app,
        "probe_agent",
        lambda *_args, **_kwargs: AgentProbe("unavailable", code="AGENT_CONNECTION_REFUSED"),
    )

    def fake_popen(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return process

    monkeypatch.setattr(windows_app.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        windows_app,
        "wait_until_ready",
        lambda port, timeout, expected_version=None: (
            observed.update(
                port=port,
                timeout=timeout,
                expected_version=expected_version,
            )
            or True
        ),
    )

    assert windows_app.ensure_agent_running(args) is process
    assert "--agent" in observed["command"]
    assert observed["port"] == 8765
    assert observed["expected_version"] == windows_app.VERSION
