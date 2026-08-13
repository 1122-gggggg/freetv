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
        user32.SetForegroundWindow(window_handle)

    def is_foreground(self, handle: int) -> bool:
        self._require_windows()
        get_foreground_window = ctypes.windll.user32.GetForegroundWindow
        get_foreground_window.argtypes = ()
        get_foreground_window.restype = wintypes.HWND
        current = get_foreground_window()
        return int(current or 0) == handle

    def bring_launcher_to_foreground(self) -> None:
        self._require_windows()
        handle = self._window_handle_with_title("MY TV")
        if handle is None:
            return
        user32 = ctypes.windll.user32
        user32.ShowWindow(wintypes.HWND(handle), SW_RESTORE)
        user32.SetForegroundWindow(wintypes.HWND(handle))

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
