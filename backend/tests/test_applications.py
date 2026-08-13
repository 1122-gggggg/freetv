from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.applications.manager import ApplicationManager
from app.commands.ports import CommandExecutionError
from app.config import ApplicationSettings, Settings, UrlSettings
from app.protocol import Command
from app.state import ActiveApp


@dataclass
class FakeProcess:
    pid: int = 123
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


@dataclass
class FakeWindows:
    minimized: list[int] = field(default_factory=list)
    maximized: list[int] = field(default_factory=list)
    brought_launcher_forward: int = 0
    window_for_pid: int | None = 900

    def find_window_for_pid(self, pid: int, timeout_seconds: float) -> int | None:
        return self.window_for_pid

    def minimize(self, handle: int) -> None:
        self.minimized.append(handle)

    def maximize(self, handle: int) -> None:
        self.maximized.append(handle)

    def bring_launcher_to_foreground(self) -> None:
        self.brought_launcher_forward += 1


@dataclass
class FakeInput:
    commands: list[Command] = field(default_factory=list)

    def send_command(self, command: Command) -> None:
        self.commands.append(command)


def make_manager(*, brave: Path | None = Path("C:/Apps/brave.exe")) -> tuple[ApplicationManager, FakeLauncher, FakeWindows, FakeInput]:
    launcher = FakeLauncher()
    windows = FakeWindows()
    input_controller = FakeInput()
    settings = Settings(
        applications=ApplicationSettings(),
        urls=UrlSettings(browser="https://example.test/"),
    )
    manager = ApplicationManager(
        settings,
        executable_paths={"brave": brave, "edge": Path("C:/Apps/msedge.exe"), "browser": None},
        process_launcher=launcher,
        windows=windows,
        input_controller=input_controller,
    )
    return manager, launcher, windows, input_controller


def test_youtube_uses_tracked_brave_process_and_argument_array() -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager()

        await manager.open(ActiveApp.YOUTUBE)

        assert launcher.calls == [
            ["C:/Apps/brave.exe", "--new-window", "--start-maximized", "https://www.youtube.com/"]
        ]
        assert windows.maximized == [900]
        assert manager.active_app is ActiveApp.YOUTUBE

    import asyncio

    asyncio.run(scenario())


def test_home_minimizes_only_the_tracked_window_and_restores_launcher() -> None:
    async def scenario() -> None:
        manager, _, windows, _ = make_manager()
        await manager.open(ActiveApp.YOUTUBE)

        await manager.return_home()

        assert windows.minimized == [900]
        assert windows.brought_launcher_forward == 1
        assert manager.active_app is ActiveApp.LAUNCHER

    import asyncio

    asyncio.run(scenario())


def test_missing_brave_returns_stable_user_facing_error() -> None:
    async def scenario() -> None:
        manager, _, _, _ = make_manager(brave=None)

        with pytest.raises(CommandExecutionError, match="Brave browser is not installed"):
            await manager.open(ActiveApp.YOUTUBE)

    import asyncio

    asyncio.run(scenario())


def test_forwarding_only_uses_fixed_command_mapping() -> None:
    async def scenario() -> None:
        manager, _, _, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)

        await manager.forward_command(Command.NAV_LEFT)

        assert input_controller.commands == [Command.NAV_LEFT]

    import asyncio

    asyncio.run(scenario())


def test_shutdown_terminates_only_the_child_started_by_controller() -> None:
    async def scenario() -> None:
        manager, launcher, _, _ = make_manager()
        await manager.open(ActiveApp.YOUTUBE)

        await manager.shutdown()

        assert launcher.process.terminated

    import asyncio

    asyncio.run(scenario())
