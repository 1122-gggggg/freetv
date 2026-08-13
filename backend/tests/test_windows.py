from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from app.system.windows import SW_RESTORE, WindowsWindowController


def handle_value(handle: object) -> int:
    return int(getattr(handle, "value", handle) or 0)


@dataclass
class FakeUser32:
    iconic: bool
    show_calls: list[tuple[int, int]] = field(default_factory=list)
    foreground_calls: list[int] = field(default_factory=list)

    def IsIconic(self, handle: object) -> bool:
        return self.iconic

    def ShowWindow(self, handle: object, action: int) -> None:
        self.show_calls.append((handle_value(handle), action))

    def SetForegroundWindow(self, handle: object) -> None:
        self.foreground_calls.append(handle_value(handle))


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
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32))

    WindowsWindowController().activate(123)

    assert user32.show_calls == []
    assert user32.foreground_calls == [123]


@pytest.mark.skipif(os.name != "nt", reason="Windows window APIs are only available on Windows.")
def test_activate_restores_a_minimized_window(monkeypatch) -> None:
    user32 = FakeUser32(iconic=True)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32))

    WindowsWindowController().activate(123)

    assert user32.show_calls == [(123, SW_RESTORE)]
    assert user32.foreground_calls == [123]


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
