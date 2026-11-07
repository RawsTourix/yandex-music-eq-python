"""Single-instance Windows application guard and local show-window notification.

A named Windows mutex is the authoritative single-instance lock within the
interactive logon session. Qt's local socket is *only* an IPC signal to reveal
the existing window; failure to connect must never allow a second instance.
"""
from __future__ import annotations

import ctypes
import os

from PySide6.QtNetwork import QLocalServer, QLocalSocket

MUTEX_NAME = r"Local\RawsTourix.YandexMusicEQ.SingleInstance"
IPC_NAME = "RawsTourix.YandexMusicEQ.ShowWindow"
ERROR_ALREADY_EXISTS = 183


class InstanceError(RuntimeError):
    pass


class WindowsInstanceMutex:
    """Hold the kernel mutex handle for the entire lifetime of the GUI process."""

    def __init__(self):
        self.handle = None
        self._kernel32 = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            raise InstanceError(
                f"Не удалось создать блокировку процесса (Win32: {ctypes.get_last_error()})"
            )
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._kernel32 = kernel32
        self.handle = handle
        return True

    def release(self):
        if self.handle is not None and self._kernel32 is not None:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


def notify_running_instance() -> bool:
    """Best-effort wake-up; the mutex, not this socket, enforces uniqueness."""
    for _ in range(5):
        socket = QLocalSocket()
        socket.connectToServer(IPC_NAME)
        if socket.waitForConnected(250):
            socket.write(b"SHOW\n")
            socket.waitForBytesWritten(250)
            socket.disconnectFromServer()
            return True
        socket.abort()
    return False


class ActivationServer:
    def __init__(self, on_show):
        self.server = QLocalServer()
        self._on_show = on_show
        self._clients = set()
        self.server.newConnection.connect(self._accept)

    def start(self):
        if not self.server.listen(IPC_NAME):
            # Windows named pipes do not leave stale socket files behind.
            # Never forcibly remove a live server's endpoint.
            raise InstanceError(f"Не удалось запустить локальный IPC: {self.server.errorString()}")

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._clients.add(socket)
            socket.readyRead.connect(lambda sock=socket: self._receive(sock))
            socket.disconnected.connect(lambda sock=socket: self._cleanup(sock))
            if socket.bytesAvailable():
                self._receive(socket)

    def _receive(self, socket):
        if bytes(socket.readAll()).strip() == b"SHOW":
            self._on_show()

    def _cleanup(self, socket):
        self._clients.discard(socket)
        socket.deleteLater()

    def close(self):
        self.server.close()
        for socket in list(self._clients):
            socket.abort()
        self._clients.clear()
