from __future__ import annotations

import pytest

from app.system.factory import build_platform_controllers
from app.system.input import WindowsInputController
from app.system.posix import PosixInputController, PosixWindowController
from app.system.windows import WindowsWindowController


def test_factory_selects_windows_controllers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.system.factory.os.name", "nt")
    controllers = build_platform_controllers()
    assert isinstance(controllers.input, WindowsInputController)
    assert isinstance(controllers.windows, WindowsWindowController)


def test_factory_selects_posix_controllers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.system.factory.os.name", "posix")
    controllers = build_platform_controllers()
    assert isinstance(controllers.input, PosixInputController)
    assert isinstance(controllers.windows, PosixWindowController)
