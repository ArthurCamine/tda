from __future__ import annotations

from types import SimpleNamespace

import pytest

from tda_companion import installation_lock


class _Function:
    def __init__(self, value=None):
        self.value = value
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.value


def _kernel(wait_result: int):
    return SimpleNamespace(
        CreateMutexW=_Function(123),
        WaitForSingleObject=_Function(wait_result),
        ReleaseMutex=_Function(1),
        CloseHandle=_Function(1),
    )


def test_non_windows_reconcile_lock_is_noop(monkeypatch):
    monkeypatch.setattr(installation_lock.os, "name", "posix")
    entered = False
    with installation_lock.installation_reconcile_lock():
        entered = True
    assert entered is True


def test_windows_reconcile_lock_releases_and_closes_handle(monkeypatch):
    kernel = _kernel(installation_lock._WAIT_OBJECT_0)
    monkeypatch.setattr(installation_lock.os, "name", "nt")
    monkeypatch.setattr(
        installation_lock.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: kernel,
        raising=False,
    )

    with installation_lock.installation_reconcile_lock(timeout_seconds=0.25):
        pass

    assert kernel.CreateMutexW.calls
    assert kernel.CreateMutexW.calls[0][2] == installation_lock._INSTALLATION_MUTEX
    assert kernel.WaitForSingleObject.calls == [(123, 250)]
    assert kernel.ReleaseMutex.calls == [(123,)]
    assert kernel.CloseHandle.calls == [(123,)]


def test_windows_agent_bootstrap_uses_separate_mutex(monkeypatch):
    kernel = _kernel(installation_lock._WAIT_OBJECT_0)
    monkeypatch.setattr(installation_lock.os, "name", "nt")
    monkeypatch.setattr(
        installation_lock.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: kernel,
        raising=False,
    )

    with installation_lock.agent_bootstrap_lock(timeout_seconds=0.5):
        pass

    assert kernel.CreateMutexW.calls[0][2] == installation_lock._AGENT_BOOTSTRAP_MUTEX
    assert kernel.WaitForSingleObject.calls == [(123, 500)]
    assert kernel.ReleaseMutex.calls == [(123,)]
    assert kernel.CloseHandle.calls == [(123,)]


def test_windows_reconcile_lock_times_out_without_running_repair(monkeypatch):
    kernel = _kernel(installation_lock._WAIT_TIMEOUT)
    monkeypatch.setattr(installation_lock.os, "name", "nt")
    monkeypatch.setattr(
        installation_lock.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: kernel,
        raising=False,
    )

    with pytest.raises(installation_lock.InstallationLockError, match="INSTALLATION_LOCK_TIMEOUT"):
        with installation_lock.installation_reconcile_lock(timeout_seconds=0.1):
            pytest.fail("repair body must not run without the installation lock")

    assert kernel.ReleaseMutex.calls == []
    assert kernel.CloseHandle.calls == [(123,)]
