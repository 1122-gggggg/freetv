from __future__ import annotations

import os
from dataclasses import dataclass

from app.system.input import WindowsInputController
from app.system.posix import (
    PosixInputController,
    PosixPowerController,
    PosixVolumeController,
    PosixWindowController,
)
from app.system.power import WindowsPowerController
from app.system.volume import WindowsVolumeController
from app.system.windows import WindowsWindowController


@dataclass(slots=True)
class PlatformControllers:
    input: WindowsInputController | PosixInputController
    volume: WindowsVolumeController | PosixVolumeController
    power: WindowsPowerController | PosixPowerController
    windows: WindowsWindowController | PosixWindowController


def build_platform_controllers() -> PlatformControllers:
    if os.name == "nt":
        return PlatformControllers(
            input=WindowsInputController(),
            volume=WindowsVolumeController(),
            power=WindowsPowerController(),
            windows=WindowsWindowController(),
        )
    return PlatformControllers(
        input=PosixInputController(),
        volume=PosixVolumeController(),
        power=PosixPowerController(),
        windows=PosixWindowController(),
    )
