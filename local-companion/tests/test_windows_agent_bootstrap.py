from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tda_companion.agent_connection import AgentProbe
from tda_companion.single_active_version import ReconcileResult
from tda_companion import windows_app


def _args(tmp_path):
    return SimpleNamespace(
        port=8765,
        state_root=tmp_path / "State",
        data_root=tmp_path / "Data",
        logs_root=tmp_path / "Logs",
        origins=frozenset({windows_app.PRODUCTION_ORIGIN}),
        startup=False,
        agent=False,
    )


def _no_redirect():
    return ReconcileResult(applied=False, target_version=windows_app.VERSION)


@pytest.mark.parametrize("state", ["exact", "foreign", "incompatible"])
def test_existing_exact_or_unowned_listener_is_never_blindly_replaced(monkeypatch, tmp_path, state: str):
    args = _args(tmp_path)
    reconciled: list[bool] = []
    monkeypatch.setattr(
        windows_app,
        "_reconcile_installation",
        lambda _paths: (reconciled.append(True) or _no_redirect()),
    )
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
    assert reconciled == [True]


def test_old_compatible_agent_is_not_accepted_as_operational_fallback(monkeypatch, tmp_path):
    args = _args(tmp_path)
    monkeypatch.setattr(windows_app, "_reconcile_installation", lambda _paths: _no_redirect())
    monkeypatch.setattr(
        windows_app,
        "probe_agent",
        lambda *_args, **_kwargs: AgentProbe(
            "compatible",
            {"service_version": "0.3.4", "pid": 9320, "port": 8765},
            "AGENT_VERSION_MISMATCH",
        ),
    )

    with pytest.raises(RuntimeError, match="STALE_AGENT_VERSION_REMAINS"):
        windows_app.ensure_agent_running(args)


def test_bootstrap_refuses_to_spawn_when_this_binary_must_redirect_forward(monkeypatch, tmp_path):
    args = _args(tmp_path)
    newer = tmp_path / "TDA" / "Companion" / "versions" / "0.3.9" / "TDACompanion.exe"
    monkeypatch.setattr(
        windows_app,
        "_reconcile_installation",
        lambda _paths: ReconcileResult(
            applied=False,
            target_version=windows_app.VERSION,
            redirect_executable=newer,
        ),
    )
    monkeypatch.setattr(
        windows_app.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("obsolete binary must not spawn its own Agent"),
    )

    with pytest.raises(RuntimeError, match="ACTIVE_VERSION_REDIRECT_REQUIRED"):
        windows_app.ensure_agent_running(args)


def test_unavailable_agent_spawns_once_inside_bootstrap_lock(monkeypatch, tmp_path):
    args = _args(tmp_path)
    process = SimpleNamespace(poll=lambda: None)
    observed = {"lock_entered": 0, "lock_exited": 0}

    monkeypatch.setattr(windows_app, "_reconcile_installation", lambda _paths: _no_redirect())
    monkeypatch.setattr(
        windows_app,
        "probe_agent",
        lambda *_args, **_kwargs: AgentProbe("unavailable", code="AGENT_CONNECTION_REFUSED"),
    )

    @contextmanager
    def fake_bootstrap_lock():
        observed["lock_entered"] += 1
        try:
            yield
        finally:
            observed["lock_exited"] += 1

    monkeypatch.setattr(windows_app, "agent_bootstrap_lock", fake_bootstrap_lock)

    def fake_popen(command, **kwargs):
        assert observed["lock_entered"] == 1
        assert observed["lock_exited"] == 0
        observed["command"] = command
        observed["kwargs"] = kwargs
        return process

    monkeypatch.setattr(windows_app.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        windows_app,
        "wait_until_ready",
        lambda port, timeout, expected_version=None: (
            observed.update(port=port, timeout=timeout, expected_version=expected_version) or True
        ),
    )

    assert windows_app.ensure_agent_running(args) is process
    assert observed["lock_entered"] == 1
    assert observed["lock_exited"] == 1
    assert "--agent" in observed["command"]
    diagnostic_index = observed["command"].index("--diagnostic-file")
    assert observed["command"][diagnostic_index + 1].endswith("last-agent-bootstrap.txt")
    assert observed["port"] == 8765
    assert observed["expected_version"] == windows_app.VERSION


def test_child_agent_exit_surfaces_sanitized_child_diagnostic(monkeypatch, tmp_path):
    args = _args(tmp_path)
    observed: dict[str, object] = {}

    monkeypatch.setattr(windows_app, "_reconcile_installation", lambda _paths: _no_redirect())
    monkeypatch.setattr(
        windows_app,
        "probe_agent",
        lambda *_args, **_kwargs: AgentProbe("unavailable", code="AGENT_CONNECTION_REFUSED"),
    )

    @contextmanager
    def fake_bootstrap_lock():
        yield

    monkeypatch.setattr(windows_app, "agent_bootstrap_lock", fake_bootstrap_lock)

    def fake_popen(command, **_kwargs):
        diagnostic_index = command.index("--diagnostic-file")
        diagnostic = windows_app.Path(command[diagnostic_index + 1])
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        diagnostic.write_text("FAILED:RuntimeError.DATA_ROOT_IN_USE\n", encoding="utf-8")
        observed["diagnostic"] = diagnostic
        return SimpleNamespace(poll=lambda: 1, returncode=1)

    monkeypatch.setattr(windows_app.subprocess, "Popen", fake_popen)

    with pytest.raises(
        RuntimeError,
        match=r"LOCAL_AGENT_EXITED:1:FAILED:RuntimeError\.DATA_ROOT_IN_USE",
    ):
        windows_app.ensure_agent_running(args)

    assert observed["diagnostic"] == tmp_path / "Cache" / "diagnostics" / "last-agent-bootstrap.txt"
