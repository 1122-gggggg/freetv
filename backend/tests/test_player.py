from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.commands.ports import CommandExecutionError
from app.player.channels import ChannelManager, load_channels
from app.player.mpv import MpvController


@dataclass
class FakeProcess:
    pid: int = 456
    terminated: bool = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> None:
        return None


@dataclass
class FakeLauncher:
    calls: list[list[str]] = field(default_factory=list)
    process: FakeProcess = field(default_factory=FakeProcess)

    def __call__(self, arguments: list[str]) -> FakeProcess:
        self.calls.append(arguments)
        return self.process


def write_channels(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "id": "one",
                    "number": 1,
                    "name": "News",
                    "url": "https://example.test/one.m3u8",
                    "enabled": True,
                },
                {
                    "id": "two",
                    "number": 2,
                    "name": "Sports",
                    "url": "https://example.test/two.m3u8",
                    "enabled": True,
                },
                {
                    "id": "off",
                    "number": 3,
                    "name": "Off Air",
                    "url": "https://example.test/off.m3u8",
                    "enabled": False,
                },
            ]
        ),
        encoding="utf-8",
    )


def test_channel_switching_skips_disabled_channels_and_wraps(tmp_path) -> None:
    path = tmp_path / "channels.json"
    write_channels(path)
    channels = ChannelManager(load_channels(path))

    assert channels.current.number == 1
    assert channels.move(1).number == 2
    assert channels.move(1).number == 1
    assert channels.move(-1).number == 2


def test_channel_config_rejects_duplicate_numbers(tmp_path) -> None:
    path = tmp_path / "channels.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "one",
                    "number": 1,
                    "name": "One",
                    "url": "https://example.test/one.m3u8",
                    "enabled": True,
                },
                {
                    "id": "two",
                    "number": 1,
                    "name": "Two",
                    "url": "https://example.test/two.m3u8",
                    "enabled": True,
                },
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unique"):
        load_channels(path)


def test_mpv_loads_initial_channel_and_switches_with_json_ipc(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "channels.json"
        write_channels(path)
        launcher = FakeLauncher()
        ipc_commands: list[list[object]] = []
        controller = MpvController(
            ChannelManager(load_channels(path)),
            mpv_path=Path("C:/Apps/mpv.exe"),
            process_launcher=launcher,
            ipc_sender=ipc_commands.append,
            pipe_name=r"\\.\pipe\test-mpv",
        )

        number, name = await controller.open()
        changed_number, changed_name = await controller.change_channel(1)

        assert (number, name) == (1, "News")
        assert launcher.calls == [
            [
                "C:/Apps/mpv.exe",
                "--fullscreen",
                "--force-window=yes",
                "--input-ipc-server=\\\\.\\pipe\\test-mpv",
                "https://example.test/one.m3u8",
            ]
        ]
        assert (changed_number, changed_name) == (2, "Sports")
        assert ipc_commands == [
            ["loadfile", "https://example.test/two.m3u8", "replace"],
            ["show-text", "頻道 02\nSports", 3000],
        ]

    asyncio.run(scenario())


def test_mpv_missing_returns_explicit_error(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "channels.json"
        write_channels(path)
        controller = MpvController(ChannelManager(load_channels(path)), mpv_path=None)

        with pytest.raises(CommandExecutionError, match="未安裝或尚未設定 mpv"):
            await controller.open()

    asyncio.run(scenario())


def test_mpv_preserves_current_channel_when_load_command_fails(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "channels.json"
        write_channels(path)
        channels = ChannelManager(load_channels(path))

        def unavailable_ipc(_: list[object]) -> None:
            raise OSError("pipe unavailable")

        controller = MpvController(
            channels,
            mpv_path=Path("C:/Apps/mpv.exe"),
            process_launcher=FakeLauncher(),
            ipc_sender=unavailable_ipc,
        )
        await controller.open()

        with pytest.raises(CommandExecutionError, match="mpv 未接受這個控制指令"):
            await controller.change_channel(1)

        assert channels.current.number == 1

    asyncio.run(scenario())
