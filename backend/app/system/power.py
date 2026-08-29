from __future__ import annotations

import ctypes
import os

from app.commands.ports import CommandExecutionError


class WindowsPowerController:
    async def sleep(self) -> None:
        if os.name != "nt":
            raise CommandExecutionError("windows_only", "僅能在 Windows 上使用休眠控制。")
        result = ctypes.windll.powrprof.SetSuspendState(False, True, False)
        if not result:
            raise CommandExecutionError("sleep_failed", "Windows 無法進入休眠。")
