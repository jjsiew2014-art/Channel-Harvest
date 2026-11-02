"""
single_instance.py
Single-instance application guard for Channel Harvest.

Prevents duplicate application launches using Qt local socket IPC (QLocalServer / QLocalSocket)
and Windows Named Mutex. When a secondary instance attempts to launch, it signals the primary
instance to bring its window to the foreground, and then terminates cleanly with exit code 0.
"""

import getpass
import os
import sys
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstanceManager(QObject):
    """
    Manages application single-instance locking and IPC activation.

    Signals:
        activate_requested: Emitted when a secondary instance attempts to launch.
    """
    activate_requested = Signal()

    def __init__(self, key: Optional[str] = None):
        super().__init__()
        user_name = os.environ.get("USERNAME") or os.environ.get("USER") or getpass.getuser() or "default"
        self.key = key or f"ChannelHarvest_SingleInstance_{user_name}"
        self.server: Optional[QLocalServer] = None
        self._mutex_handle = None

    def is_already_running(self) -> bool:
        """
        Determines whether another instance of Channel Harvest is currently running.

        Returns:
            bool: True if another instance is active (and has been signaled to activate),
                  False if this is the primary instance.
        """
        # 1. Primary probe: Attempt to connect to an existing QLocalServer
        sock = QLocalSocket()
        sock.connectToServer(self.key)
        if sock.waitForConnected(500):
            try:
                sock.write(b"ACTIVATE\n")
                sock.waitForBytesWritten(500)
            except Exception:
                pass
            sock.disconnectFromServer()
            return True

        # 2. Windows Named Mutex (prevents race conditions if two instances start at the exact same millisecond)
        if sys.platform == "win32":
            try:
                import ctypes
                mutex_name = f"Local\\{self.key}_Mutex"
                self._mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
                last_error = ctypes.windll.kernel32.GetLastError()
                ERROR_ALREADY_EXISTS = 183
                if last_error == ERROR_ALREADY_EXISTS:
                    # Mutex is already held by another process; retry socket connection briefly
                    import time
                    for _ in range(5):
                        sock = QLocalSocket()
                        sock.connectToServer(self.key)
                        if sock.waitForConnected(300):
                            try:
                                sock.write(b"ACTIVATE\n")
                                sock.waitForBytesWritten(300)
                            except Exception:
                                pass
                            sock.disconnectFromServer()
                            break
                        time.sleep(0.1)
                    return True
            except Exception:
                pass

        # 3. Clean up any stale pipe / server file leftover from an unexpected crash
        QLocalServer.removeServer(self.key)

        # 4. Bind as the primary instance server
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        success = self.server.listen(self.key)
        if not success:
            # If listen failed, another instance likely claimed the port just now
            return True

        return False

    def _on_new_connection(self) -> None:
        """Handles connection from a secondary instance attempting to launch."""
        if not self.server:
            return
        client = self.server.nextPendingConnection()
        if client:
            client.disconnectFromServer()
        self.activate_requested.emit()

    def close(self) -> None:
        """Releases the local server and mutex handle."""
        if self.server:
            try:
                self.server.close()
            except Exception:
                pass
            QLocalServer.removeServer(self.key)
            self.server = None

        if self._mutex_handle and sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None
