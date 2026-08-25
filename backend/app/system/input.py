from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from app.commands.ports import CommandExecutionError
from app.protocol import Command, PointerAction, PointerActionMessage

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

VK_UP = 0x26
VK_DOWN = 0x28
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_MENU = 0x12
VK_SPACE = 0x20
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1

_COMMAND_KEYS: dict[Command, int] = {
    Command.NAV_UP: VK_UP,
    Command.NAV_DOWN: VK_DOWN,
    Command.NAV_LEFT: VK_LEFT,
    Command.NAV_RIGHT: VK_RIGHT,
    Command.OK: VK_RETURN,
    Command.BACK: VK_ESCAPE,
    Command.PLAY_PAUSE: VK_SPACE,
    Command.NEXT: VK_MEDIA_NEXT_TRACK,
    Command.PREVIOUS: VK_MEDIA_PREV_TRACK,
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


class WindowsInputController:
    async def pointer(self, message: PointerActionMessage) -> None:
        self._require_windows()
        if message.action is PointerAction.MOVE:
            self._send(self._mouse(message.dx, message.dy, 0, MOUSEEVENTF_MOVE))
        elif message.action is PointerAction.TAP:
            self._send(
                self._mouse(0, 0, 0, MOUSEEVENTF_LEFTDOWN), self._mouse(0, 0, 0, MOUSEEVENTF_LEFTUP)
            )
        elif message.action is PointerAction.DOUBLE_TAP:
            self._send(
                self._mouse(0, 0, 0, MOUSEEVENTF_LEFTDOWN),
                self._mouse(0, 0, 0, MOUSEEVENTF_LEFTUP),
                self._mouse(0, 0, 0, MOUSEEVENTF_LEFTDOWN),
                self._mouse(0, 0, 0, MOUSEEVENTF_LEFTUP),
            )
        elif message.action is PointerAction.SCROLL:
            wheel_delta = ctypes.c_uint32(message.dy * WHEEL_DELTA).value
            self._send(self._mouse(0, 0, wheel_delta, MOUSEEVENTF_WHEEL))
        else:  # pragma: no cover - Pydantic prevents unknown actions.
            raise CommandExecutionError(
                "invalid_pointer_action", "不允許這個觸控板操作。"
            )

    async def text(self, text: str) -> None:
        self._require_windows()
        events: list[INPUT] = []
        encoded = text.encode("utf-16-le")
        for offset in range(0, len(encoded), 2):
            code_unit = int.from_bytes(encoded[offset : offset + 2], "little")
            events.append(self._key(0, code_unit, KEYEVENTF_UNICODE))
            events.append(self._key(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        self._send(*events)

    def send_command(self, command: Command) -> None:
        self._require_windows()
        virtual_key = _COMMAND_KEYS.get(command)
        if virtual_key is None:
            raise CommandExecutionError(
                "unsupported_forward_command",
                "這個操作不適用於目前的應用程式。",
            )
        self._send(self._key(virtual_key, 0, 0), self._key(virtual_key, 0, KEYEVENTF_KEYUP))

    def send_browser_back(self) -> None:
        self._require_windows()
        self._send(
            self._key(VK_MENU, 0, 0),
            self._key(VK_LEFT, 0, 0),
            self._key(VK_LEFT, 0, KEYEVENTF_KEYUP),
            self._key(VK_MENU, 0, KEYEVENTF_KEYUP),
        )

    @staticmethod
    def _mouse(dx: int, dy: int, mouse_data: int, flags: int) -> INPUT:
        return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dx, dy, mouse_data, flags, 0, 0))

    @staticmethod
    def _key(virtual_key: int, scan_code: int, flags: int) -> INPUT:
        return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(virtual_key, scan_code, flags, 0, 0))

    @staticmethod
    def _require_windows() -> None:
        if os.name != "nt":
            raise CommandExecutionError(
                "windows_only", "僅能在 Windows 上使用輸入控制。"
            )

    @staticmethod
    def _send(*events: INPUT) -> None:
        if not events:
            return
        array = (INPUT * len(events))(*events)
        sent = ctypes.windll.user32.SendInput(
            len(events), ctypes.byref(array), ctypes.sizeof(INPUT)
        )
        if sent != len(events):
            raise CommandExecutionError(
                "windows_input_failed", "Windows 未接受這個輸入。"
            )
