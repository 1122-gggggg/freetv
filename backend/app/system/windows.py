from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9


class WindowsWindowController:
    """Finds and manages only a concrete browser window, never process families."""

    def find_window_for_pid(self, pid: int, timeout_seconds: float) -> int | None:
        self._require_windows()
        deadline = time.monotonic() + timeout_seconds
        while True:
            handles = self._window_handles_for_pid(pid)
            if handles:
                return handles[0]
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.1)

    def window_belongs_to_process(self, handle: int, pid: int) -> bool:
        self._require_windows()
        window_handle = wintypes.HWND(handle)
        user32 = ctypes.windll.user32
        if not user32.IsWindow(window_handle):
            return False
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window_handle, ctypes.byref(process_id))
        return process_id.value == pid

    def minimize(self, handle: int) -> None:
        self._require_windows()
        ctypes.windll.user32.ShowWindow(wintypes.HWND(handle), SW_MINIMIZE)

    def maximize(self, handle: int) -> None:
        self._require_windows()
        user32 = ctypes.windll.user32
        user32.ShowWindow(wintypes.HWND(handle), SW_MAXIMIZE)
        user32.SetForegroundWindow(wintypes.HWND(handle))

    def activate(self, handle: int) -> None:
        self._require_windows()
        user32 = ctypes.windll.user32
        window_handle = wintypes.HWND(handle)
        if user32.IsIconic(window_handle):
            user32.ShowWindow(window_handle, SW_RESTORE)
        if hasattr(user32, "BringWindowToTop"):
            user32.BringWindowToTop(window_handle)
        user32.SetForegroundWindow(window_handle)

    def is_foreground(self, handle: int) -> bool:
        self._require_windows()
        get_foreground_window = ctypes.windll.user32.GetForegroundWindow
        get_foreground_window.argtypes = ()
        get_foreground_window.restype = wintypes.HWND
        current = int(get_foreground_window() or 0)
        if current == handle:
            return True
        if current == 0:
            return False
        target_pid = wintypes.DWORD()
        current_pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(handle, ctypes.byref(target_pid))
        ctypes.windll.user32.GetWindowThreadProcessId(current, ctypes.byref(current_pid))
        return bool(target_pid.value and target_pid.value == current_pid.value)

    def bring_launcher_to_foreground(self) -> None:
        self._require_windows()
        handle = self._window_handle_with_title("我的電視")
        if handle is None:
            return
        self.activate(handle)

    def close_launcher(self) -> None:
        self._require_windows()
        handle = self._window_handle_with_title("我的電視")
        if handle is None:
            return
        ctypes.windll.user32.PostMessageW(wintypes.HWND(handle), 0x0010, 0, 0)

    def focus_window_with_title(self, title_fragment: str) -> int | None:
        self._require_windows()
        handle = self._window_handle_with_title(title_fragment)
        if handle is None:
            return None
        self.activate(handle)
        return handle

    def _window_handles_for_pid(self, pid: int) -> list[int]:
        handles: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(handle: int, _: int) -> bool:
            process_id = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
            if process_id.value == pid and ctypes.windll.user32.IsWindowVisible(handle):
                handles.append(int(handle))
            return True

        ctypes.windll.user32.EnumWindows(callback, 0)
        return handles

    def _window_handle_with_title(self, expected_fragment: str) -> int | None:
        matched: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(handle: int, _: int) -> bool:
            user32 = ctypes.windll.user32
            if not user32.IsWindowVisible(handle):
                return True
            length = user32.GetWindowTextLengthW(handle)
            if length <= 0:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, title, len(title))
            if expected_fragment.casefold() in title.value.casefold():
                matched.append(int(handle))
                return False
            return True

        ctypes.windll.user32.EnumWindows(callback, 0)
        return matched[0] if matched else None

    @staticmethod
    def _require_windows() -> None:
        if os.name != "nt":
            raise RuntimeError("Windows window control is only available on Windows.")
