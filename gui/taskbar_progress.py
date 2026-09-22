"""
taskbar_progress.py
Windows Taskbar Progress Integration for Channel Harvest.

Provides real-time taskbar icon progress bar (green for active download,
yellow for paused, and cleared on completion/cancellation) using the
native Windows ITaskbarList3 COM interface without external third-party dependencies.
"""

import sys
from typing import Optional, Any
from PySide6.QtWidgets import QWidget


class TaskbarProgressManager:
    """
    Manages Windows Taskbar icon progress bar for a PySide6 top-level window.
    Safely no-ops on non-Windows platforms or if COM initialization is unavailable.
    """

    # Windows TBPFLAG definitions
    TBPF_NOPROGRESS    = 0x00000000
    TBPF_INDETERMINATE = 0x00000001
    TBPF_NORMAL        = 0x00000002
    TBPF_ERROR         = 0x00000004
    TBPF_PAUSED        = 0x00000008

    def __init__(self, window: Optional[QWidget] = None) -> None:
        self._window = window
        self._taskbar: Optional[Any] = None
        self._set_value_fn: Optional[Any] = None
        self._set_state_fn: Optional[Any] = None
        self._current_state = self.TBPF_NOPROGRESS
        self._last_completed: int = 0
        self._last_total: int = 100
        self._is_available = False

        self._init_com()

    def _init_com(self) -> None:
        """Initializes the ITaskbarList3 COM interface via ctypes."""
        if sys.platform != "win32":
            return

        try:
            import ctypes
            from ctypes import wintypes, byref, c_void_p, POINTER, Structure, c_int, c_ulonglong, WINFUNCTYPE

            class GUID(Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8),
                ]

            ole32 = ctypes.windll.ole32
            # Initialize COM in single-threaded / apartment mode
            ole32.CoInitialize(None)

            clsid = GUID()
            iid = GUID()
            # CLSID_TaskbarList: {56FDF344-FD6D-11d0-958A-006097C9A090}
            ole32.IIDFromString("{56FDF344-FD6D-11D0-958A-006097C9A090}", byref(clsid))
            # IID_ITaskbarList3: {EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}
            ole32.IIDFromString("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}", byref(iid))

            p_taskbar = c_void_p()
            CLSCTX_INPROC_SERVER = 1
            hr = ole32.CoCreateInstance(byref(clsid), None, CLSCTX_INPROC_SERVER, byref(iid), byref(p_taskbar))
            if hr != 0 or not p_taskbar.value:
                return

            self._taskbar = p_taskbar
            vtable = ctypes.cast(p_taskbar, POINTER(POINTER(c_void_p))).contents

            # VTable Index 3: HrInit(this)
            try:
                hr_init_fn = WINFUNCTYPE(c_int, c_void_p)(vtable[3])
                hr_init_fn(self._taskbar)
            except Exception:
                pass

            # VTable Index 9: SetProgressValue(this, hwnd, completed, total)
            self._set_value_fn = WINFUNCTYPE(
                c_int, c_void_p, wintypes.HWND, c_ulonglong, c_ulonglong
            )(vtable[9])

            # VTable Index 10: SetProgressState(this, hwnd, flags)
            self._set_state_fn = WINFUNCTYPE(
                c_int, c_void_p, wintypes.HWND, c_int
            )(vtable[10])

            self._is_available = True
        except Exception:
            self._taskbar = None
            self._set_value_fn = None
            self._set_state_fn = None
            self._is_available = False

    @property
    def is_available(self) -> bool:
        """Returns True if Windows Taskbar progress integration is active."""
        return self._is_available

    def set_window(self, window: QWidget) -> None:
        """Assigns the parent window."""
        self._window = window

    def _get_hwnd(self) -> int:
        """Resolves the Win32 HWND from the assigned QWidget."""
        if self._window is None:
            return 0
        try:
            return int(self._window.winId())
        except Exception:
            return 0

    def set_progress(self, completed: int, total: int = 100) -> None:
        """
        Updates the taskbar progress bar value.
        If the current state is not NORMAL (e.g. NOPROGRESS), it activates NORMAL state.
        """
        if not self._is_available:
            return

        hwnd = self._get_hwnd()
        if not hwnd:
            return

        clamped_total = max(1, int(total))
        clamped_completed = max(0, min(clamped_total, int(completed)))
        self._last_completed = clamped_completed
        self._last_total = clamped_total

        try:
            if self._current_state != self.TBPF_NORMAL:
                self._current_state = self.TBPF_NORMAL
                self._set_state_fn(self._taskbar, hwnd, self.TBPF_NORMAL)

            self._set_value_fn(self._taskbar, hwnd, clamped_completed, clamped_total)
        except Exception:
            pass

    def set_state(self, state: int) -> None:
        """Sets the taskbar progress state directly using TBPFLAG values."""
        if not self._is_available:
            return

        hwnd = self._get_hwnd()
        if not hwnd:
            return

        try:
            self._current_state = state
            self._set_state_fn(self._taskbar, hwnd, state)
            if state in (self.TBPF_NORMAL, self.TBPF_PAUSED, self.TBPF_ERROR) and self._last_total > 0:
                self._set_value_fn(self._taskbar, hwnd, self._last_completed, self._last_total)
        except Exception:
            pass

    def pause(self) -> None:
        """Switches the taskbar progress bar to yellow paused state."""
        self.set_state(self.TBPF_PAUSED)

    def resume(self) -> None:
        """Restores the taskbar progress bar to active normal green state."""
        self.set_state(self.TBPF_NORMAL)

    def clear(self) -> None:
        """Removes the progress bar from the taskbar icon."""
        if not self._is_available:
            return

        hwnd = self._get_hwnd()
        if not hwnd:
            return

        try:
            self._current_state = self.TBPF_NOPROGRESS
            self._set_state_fn(self._taskbar, hwnd, self.TBPF_NOPROGRESS)
        except Exception:
            pass
