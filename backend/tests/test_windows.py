from __future__ import annotations

import asyncio
import ctypes
import os
import subprocess
import threading
from ctypes import wintypes
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from app.protocol import Command
from app.system.input import _COMMAND_KEYS, VK_F11
from app.system.windows import (
    SW_RESTORE,
    WindowsBrightnessController,
    WindowsWindowController,
)


def handle_value(handle: object) -> int:
    return int(getattr(handle, "value", handle) or 0)

@dataclass
class FakeKernel32:
    thread_id: int = 30

    def GetCurrentThreadId(self) -> int:
        return self.thread_id

@dataclass
class FakeUser32:
    iconic: bool
    foreground: int = 456
    require_thread_input: bool = False
    show_calls: list[tuple[int, int]] = field(default_factory=list)
    foreground_calls: list[int] = field(default_factory=list)
    attached_threads: set[int] = field(default_factory=set)
    attach_calls: list[tuple[int, int, bool]] = field(default_factory=list)

    def IsIconic(self, handle: object) -> bool:
        return self.iconic

    def ShowWindow(self, handle: object, action: int) -> None:
        self.show_calls.append((handle_value(handle), action))

    def GetForegroundWindow(self) -> int:
        return self.foreground

    def GetWindowThreadProcessId(self, handle: object, _: object) -> int:
        return 10 if handle_value(handle) == self.foreground else 20

    def AttachThreadInput(self, source: int, target: int, attach: bool) -> bool:
        self.attach_calls.append((source, target, attach))
        if attach:
            self.attached_threads.add(target)
        else:
            self.attached_threads.discard(target)
        return True

    def BringWindowToTop(self, _: object) -> None:
        return

    def SetForegroundWindow(self, handle: object) -> bool:
        value = handle_value(handle)
        self.foreground_calls.append(value)
        if not self.require_thread_input or self.attached_threads == {10, 20}:
            self.foreground = value
            return True
        return False

    def SetActiveWindow(self, _: object) -> None:
        return

    def SetFocus(self, _: object) -> None:
        return


@dataclass
class FakeGetForegroundWindow:
    handle: int
    restype: object = ctypes.c_int
    argtypes: object | None = None

    def __call__(self) -> int:
        if self.restype is wintypes.HWND:
            return self.handle
        return ctypes.c_int32(self.handle).value


@pytest.mark.skipif(os.name != "nt", reason="Windows window APIs are only available on Windows.")
def test_activate_preserves_a_maximized_window(monkeypatch) -> None:
    user32 = FakeUser32(iconic=False)
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(user32=user32, kernel32=FakeKernel32()),
    )

    WindowsWindowController().activate(123)

    assert user32.show_calls == []
    assert user32.foreground_calls == [123]


@pytest.mark.skipif(os.name != "nt", reason="Windows window APIs are only available on Windows.")
def test_activate_restores_a_minimized_window(monkeypatch) -> None:
    user32 = FakeUser32(iconic=True)
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(user32=user32, kernel32=FakeKernel32()),
    )

    WindowsWindowController().activate(123)

    assert user32.show_calls == [(123, SW_RESTORE)]
    assert user32.foreground_calls == [123]


@pytest.mark.skipif(os.name != "nt", reason="Windows window APIs are only available on Windows.")
def test_activate_bypasses_foreground_lock_and_detaches_input_threads(monkeypatch) -> None:
    user32 = FakeUser32(iconic=False, require_thread_input=True)
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(user32=user32, kernel32=FakeKernel32()),
    )

    WindowsWindowController().activate(123)

    assert user32.foreground == 123
    assert user32.attached_threads == set()


@pytest.mark.skipif(os.name != "nt", reason="Windows window APIs are only available on Windows.")
def test_is_foreground_preserves_pointer_sized_window_handles(monkeypatch) -> None:
    handle = 0x1_0000_0001
    get_foreground_window = FakeGetForegroundWindow(handle)
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(user32=SimpleNamespace(GetForegroundWindow=get_foreground_window)),
    )

    assert WindowsWindowController().is_foreground(handle)
    assert get_foreground_window.restype is wintypes.HWND
    assert get_foreground_window.argtypes == ()


def test_fullscreen_maps_to_windows_f11() -> None:
    assert _COMMAND_KEYS[Command.FULLSCREEN] == VK_F11


def test_windows_brightness_uses_invoke_cim_method(monkeypatch) -> None:
    calls: list[list[str]] = []

    def run(arguments: list[str], **_: object) -> SimpleNamespace:
        calls.append(arguments)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(subprocess, "run", run)

    WindowsBrightnessController()._write_level_sync(40)

    command = calls[0][-1]
    assert "Invoke-CimMethod" in command
    assert "WmiSetBrightness(1, 40)" not in command


def test_windows_brightness_does_not_block_the_event_loop(monkeypatch) -> None:
    async def scenario() -> None:
        events: list[str] = []
        release = threading.Event()

        def run(_: list[str], **__: object) -> SimpleNamespace:
            events.append("run-start")
            threading.Timer(0.1, release.set).start()
            release.wait(timeout=1)
            events.append("run-end")
            return SimpleNamespace(stdout="")

        monkeypatch.setattr(subprocess, "run", run)
        controller = WindowsBrightnessController(initial_level=50)
        controller._initialized = True

        async def pulse() -> None:
            await asyncio.sleep(0.01)
            events.append("pulse")

        level, _ = await asyncio.gather(controller.decrease(), pulse())

        assert level == 40
        assert events.index("pulse") < events.index("run-end")

    asyncio.run(scenario())
