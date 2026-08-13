from __future__ import annotations

import ctypes
import os

from app.commands.ports import CommandExecutionError


class WindowsPowerController:
    async def sleep(self) -> None:
        if os.name != "nt":
            raise CommandExecutionError(
                "windows_only", "Sleep control is only available on Windows."
            )
        result = ctypes.windll.powrprof.SetSuspendState(False, True, False)
        if not result:
            raise CommandExecutionError("sleep_failed", "Windows could not enter sleep mode.")
