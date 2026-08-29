from __future__ import annotations

from app.system.factory import PlatformControllers, build_platform_controllers
from app.system.input import WindowsInputController
from app.system.posix import (
    PosixBrightnessController,
    PosixInputController,
    PosixPowerController,
    PosixVolumeController,
    PosixWindowController,
)
from app.system.power import WindowsPowerController
from app.system.volume import WindowsVolumeController
from app.system.windows import WindowsBrightnessController, WindowsWindowController

__all__ = [
    "PlatformControllers",
    "PosixBrightnessController",
    "PosixInputController",
    "PosixPowerController",
    "PosixVolumeController",
    "PosixWindowController",
    "WindowsBrightnessController",
    "WindowsInputController",
    "WindowsPowerController",
    "WindowsVolumeController",
    "WindowsWindowController",
    "build_platform_controllers",
]
