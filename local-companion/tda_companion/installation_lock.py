from __future__ import annotations

import ctypes
import os
from contextlib import contextmanager
from ctypes import wintypes
from typing import Iterator

_MUTEX_NAME = r"Local\Faysk.TDA.Companion.InstallationReconcile"
_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_TIMEOUT = 0x00000102


class InstallationLockError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@contextmanager
def installation_reconcile_lock(timeout_seconds: float = 15.0) -> Iterator[None]:
    """Serialize installation repair across UI, Startup and Agent processes.

    Packaged Windows launches can race: Windows Startup may create the Agent at
    the same moment the user opens the UI, while an update may also be finishing.
    A named per-session mutex keeps process termination, version cleanup and
    current-version reconciliation from running concurrently.
    """
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

    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        raise InstallationLockError(
            f"INSTALLATION_LOCK_CREATE_FAILED:{ctypes.get_last_error()}"
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
            raise InstallationLockError("INSTALLATION_LOCK_TIMEOUT")
        raise InstallationLockError(f"INSTALLATION_LOCK_WAIT_FAILED:{result}")
    finally:
        if acquired:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
