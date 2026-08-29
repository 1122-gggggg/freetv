from __future__ import annotations

import os
from dataclasses import dataclass

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


@dataclass(slots=True)
class PlatformControllers:
    input: WindowsInputController | PosixInputController
    volume: WindowsVolumeController | PosixVolumeController
    brightness: WindowsBrightnessController | PosixBrightnessController
    power: WindowsPowerController | PosixPowerController
    windows: WindowsWindowController | PosixWindowController


def build_platform_controllers(*, os_name: str = os.name) -> PlatformControllers:
    if os_name == "nt":
        return PlatformControllers(
            input=WindowsInputController(),
            volume=WindowsVolumeController(),
            brightness=WindowsBrightnessController(os_name=os_name),
            power=WindowsPowerController(),
            windows=WindowsWindowController(),
        )
    return PlatformControllers(
        input=PosixInputController(),
        volume=PosixVolumeController(),
        brightness=PosixBrightnessController(),
        power=PosixPowerController(),
        windows=PosixWindowController(),
    )
