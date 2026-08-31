from __future__ import annotations

import ctypes
import os
import subprocess
from collections.abc import Callable, Sequence

from app.commands.ports import CommandExecutionError

ShutdownRunner = Callable[[Sequence[str]], object]


def _schedule_windows_shutdown(arguments: Sequence[str]) -> None:
    try:
        completed = subprocess.run(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CommandExecutionError("shutdown_failed", "Windows 無法排程關機。") from error
    if completed.returncode != 0:
        raise CommandExecutionError("shutdown_failed", "Windows 無法排程關機。")


class WindowsPowerController:
    def __init__(
        self,
        *,
        os_name: str | None = None,
        shutdown_runner: ShutdownRunner | None = None,
    ) -> None:
        self._os_name = os_name or os.name
        self._shutdown_runner = shutdown_runner or _schedule_windows_shutdown

    async def sleep(self) -> None:
        if self._os_name != "nt":
            raise CommandExecutionError("windows_only", "僅能在 Windows 上使用休眠控制。")
        result = ctypes.windll.powrprof.SetSuspendState(False, True, False)
        if not result:
            raise CommandExecutionError("sleep_failed", "Windows 無法進入休眠。")

    async def shutdown(self) -> None:
        if self._os_name != "nt":
            raise CommandExecutionError("windows_only", "僅能在 Windows 上使用關機控制。")
        self._shutdown_runner(["shutdown.exe", "/s", "/t", "5"])
