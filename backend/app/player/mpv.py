from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.commands.ports import CommandExecutionError
from app.logging import log_event
from app.player.channels import ChannelManager


class ChildProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float) -> object: ...


logger = logging.getLogger(__name__)


class MpvController:
    def __init__(
        self,
        channels: ChannelManager,
        *,
        mpv_path: Path | None,
        process_launcher: Callable[[list[str]], ChildProcess] | None = None,
        ipc_sender: Callable[[list[object]], None] | None = None,
        pipe_name: str | None = None,
    ) -> None:
        self._channels = channels
        self._mpv_path = mpv_path
        self._launch_process = process_launcher or self._default_process_launcher
        self._pipe_name = pipe_name or rf"\\.\pipe\pc-tv-box-mpv-{os.getpid()}"
        self._send_ipc = ipc_sender or self._default_ipc_sender
        self._process: ChildProcess | None = None

    async def open(self) -> tuple[int, str]:
        channel = self._channels.current
        if self._mpv_path is None:
            raise CommandExecutionError(
                "mpv_not_found",
                "mpv is not installed or configured. Install mpv, then set its path in Settings.",
            )

        if self._process is not None and self._process.poll() is None:
            await self._send_command(["loadfile", channel.url, "replace"])
        else:
            arguments = [
                self._mpv_path.as_posix(),
                "--fullscreen",
                "--force-window=yes",
                f"--input-ipc-server={self._pipe_name}",
                channel.url,
            ]
            try:
                self._process = self._launch_process(arguments)
            except OSError as error:
                raise CommandExecutionError("mpv_launch_failed", "Could not start mpv.") from error
            log_event(logger, "mpv_started", process_id=self._process.pid, channel=channel.id)
        return channel.number, channel.name

    async def close(self) -> None:
        if self._process is None or self._process.poll() is not None:
            self._process = None
            return
        try:
            self._process.terminate()
            await asyncio.to_thread(self._process.wait, 2.0)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            self._process = None

    async def toggle_pause(self) -> None:
        await self._send_command(["cycle", "pause"])

    async def next(self) -> None:
        await self._send_command(["playlist-next", "force"])

    async def previous(self) -> None:
        await self._send_command(["playlist-prev", "force"])

    async def change_channel(self, direction: int) -> tuple[int, str]:
        channel = self._channels.preview_move(direction)
        await self._send_command(["loadfile", channel.url, "replace"])
        self._channels.move(direction)
        try:
            await self._send_command(
                ["show-text", f"CH {channel.number:02d}\n{channel.name}", 3000]
            )
        except CommandExecutionError:
            log_event(logger, "mpv_osd_failed", channel=channel.id, number=channel.number)
        log_event(logger, "channel_changed", channel=channel.id, number=channel.number)
        return channel.number, channel.name

    async def set_volume(self, level: int) -> None:
        if not 0 <= level <= 100:
            raise ValueError("Volume must be between 0 and 100.")
        await self._send_command(["set_property", "volume", level])

    async def set_muted(self, muted: bool) -> None:
        await self._send_command(["set_property", "mute", muted])

    async def _send_command(self, command: list[object]) -> None:
        if self._process is None or self._process.poll() is not None:
            raise CommandExecutionError("mpv_not_running", "Live TV is not running.")
        try:
            await asyncio.to_thread(self._send_ipc, command)
        except CommandExecutionError:
            raise
        except OSError as error:
            raise CommandExecutionError(
                "mpv_ipc_unavailable", "mpv did not accept the requested control."
            ) from error

    def _default_ipc_sender(self, command: list[object]) -> None:
        payload = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8") + b"\n"
        deadline = time.monotonic() + 1.5
        while True:
            try:
                with open(self._pipe_name, "r+b", buffering=0) as connection:
                    connection.write(payload)
                    connection.flush()
                    return
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise error
                time.sleep(0.1)

    @staticmethod
    def _default_process_launcher(arguments: list[str]) -> ChildProcess:
        return subprocess.Popen(arguments)  # noqa: S603 - arguments are controlled local configuration.
