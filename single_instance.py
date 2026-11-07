"""One interactive-Windows-session process, with native wake-up signalling.

The named mutex is the authoritative single-instance guard. A named auto-reset
Windows event lets a second launch request that the primary application reveal
its window; the GUI polls it with a cheap Qt timer. No local socket race.
"""
from __future__ import annotations

import ctypes
import os
import time

MUTEX_NAME = r"Local\RawsTourix.YandexMusicEQ.SingleInstance"
EVENT_NAME = r"Local\RawsTourix.YandexMusicEQ.ShowWindow"
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258


class InstanceError(RuntimeError):
    pass


def _kernel32():
    if os.name != "nt":
        raise InstanceError("Управление единственным экземпляром поддерживается в Windows")
    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    dll.CreateMutexW.restype = ctypes.c_void_p
    dll.CreateEventW.argtypes = [
        ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p,
    ]
    dll.CreateEventW.restype = ctypes.c_void_p
    dll.OpenEventW.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_wchar_p]
    dll.OpenEventW.restype = ctypes.c_void_p
    dll.SetEvent.argtypes = [ctypes.c_void_p]
    dll.SetEvent.restype = ctypes.c_bool
    dll.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    dll.WaitForSingleObject.restype = ctypes.c_ulong
    dll.CloseHandle.argtypes = [ctypes.c_void_p]
    dll.CloseHandle.restype = ctypes.c_bool
    return dll


class WindowsInstanceMutex:
    """Keep the kernel handle open for the lifetime of the primary process."""

    def __init__(self):
        self.handle = None
        self._kernel = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        kernel = _kernel32()
        ctypes.set_last_error(0)
        handle = kernel.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            raise InstanceError(
                f"Не удалось создать блокировку процесса (Win32: {ctypes.get_last_error()})"
            )
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel.CloseHandle(handle)
            return False
        self._kernel = kernel
        self.handle = handle
        return True

    def release(self):
        if self.handle is not None and self._kernel is not None:
            self._kernel.CloseHandle(self.handle)
            self.handle = None


class ActivationEvent:
    """The first process owns an auto-reset event used to request ShowWindow."""

    def __init__(self):
        self.handle = None
        self._kernel = None

    def create(self):
        kernel = _kernel32()
        handle = kernel.CreateEventW(None, False, False, EVENT_NAME)
        if not handle:
            raise InstanceError(
                f"Не удалось создать событие активации (Win32: {ctypes.get_last_error()})"
            )
        self._kernel = kernel
        self.handle = handle

    def consume(self) -> bool:
        if self.handle is None or self._kernel is None:
            return False
        result = self._kernel.WaitForSingleObject(self.handle, 0)
        if result == WAIT_OBJECT_0:
            return True
        if result == WAIT_TIMEOUT:
            return False
        raise InstanceError(
            f"Ошибка ожидания события активации (Win32: {ctypes.get_last_error()})"
        )

    def close(self):
        if self.handle is not None and self._kernel is not None:
            self._kernel.CloseHandle(self.handle)
            self.handle = None


def notify_running_instance() -> bool:
    """Send wake-up signal to the first process without launching another GUI."""
    if os.name != "nt":
        return False
    kernel = _kernel32()
    # The primary may still be starting between mutex and event creation.
    for attempt in range(8):
        handle = kernel.OpenEventW(EVENT_MODIFY_STATE, False, EVENT_NAME)
        if handle:
            try:
                return bool(kernel.SetEvent(handle))
            finally:
                kernel.CloseHandle(handle)
        if attempt < 7:
            time.sleep(.15)
    return False
