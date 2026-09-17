from __future__ import annotations

import ctypes
import os
from contextlib import contextmanager
from ctypes import wintypes
from typing import Iterator

_INSTALLATION_MUTEX = r"Local\Faysk.TDA.Companion.InstallationReconcile"
_AGENT_BOOTSTRAP_MUTEX = r"Local\Faysk.TDA.Companion.AgentBootstrap"
_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_TIMEOUT = 0x00000102


class InstallationLockError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@contextmanager
def _named_lock(name: str, timeout_seconds: float, code_prefix: str) -> Iterator[None]:
    if os.name != "nt":
        yield
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise InstallationLockError(
            f"{code_prefix}_CREATE_FAILED:{ctypes.get_last_error()}"
        )

    acquired = False
    try:
        milliseconds = max(0, min(int(timeout_seconds * 1000), 0xFFFFFFFF))
        result = int(kernel32.WaitForSingleObject(handle, milliseconds))
        if result in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
            acquired = True
            yield
            return
        if result == _WAIT_TIMEOUT:
            raise InstallationLockError(f"{code_prefix}_TIMEOUT")
        raise InstallationLockError(f"{code_prefix}_WAIT_FAILED:{result}")
    finally:
        if acquired:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


@contextmanager
def installation_reconcile_lock(timeout_seconds: float = 15.0) -> Iterator[None]:
    """Serialize mutation of the installed Companion tree."""
    with _named_lock(_INSTALLATION_MUTEX, timeout_seconds, "INSTALLATION_LOCK"):
        yield


@contextmanager
def agent_bootstrap_lock(timeout_seconds: float = 15.0) -> Iterator[None]:
    """Serialize probe/spawn so simultaneous UI launches create one Agent.

    This lock is intentionally separate from installation reconciliation. The UI
    may hold it while spawning the Agent; the child Agent is then free to acquire
    the installation mutex during its own bootstrap without deadlocking its
    parent.
    """
    with _named_lock(_AGENT_BOOTSTRAP_MUTEX, timeout_seconds, "AGENT_BOOTSTRAP_LOCK"):
        yield
