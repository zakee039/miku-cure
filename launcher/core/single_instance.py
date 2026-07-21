"""Windows 单实例锁（命名互斥量）。"""
from __future__ import annotations

import sys


class SingleInstance:
    def __init__(self, name: str = "Local\\MikuCureLauncherMutex") -> None:
        self._name = name
        self._handle = None

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.CreateMutexW(None, False, self._name)
            last = kernel32.GetLastError()
            self._handle = handle
            # ERROR_ALREADY_EXISTS = 183
            return last != 183
        except Exception:
            return True

    def release(self) -> None:
        if sys.platform != "win32" or not self._handle:
            return
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self._handle)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._handle = None
