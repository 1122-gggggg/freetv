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
    exit_code: int | None = None

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> None:
        return None


@dataclass
class FakeLauncher:
    calls: list[list[str]] = field(default_factory=list)
    process: FakeProcess = field(default_factory=FakeProcess)
    fail_next_launch: bool = False

    def __call__(self, arguments: list[str]) -> FakeProcess:
        self.calls.append(arguments)
        if self.fail_next_launch:
            self.fail_next_launch = False
            raise OSError("launch failed")
        return self.process


@dataclass
class FakeWindows:
    minimized: list[int] = field(default_factory=list)
    maximized: list[int] = field(default_factory=list)
    activated: list[int] = field(default_factory=list)
    brought_launcher_forward: int = 0
    window_for_pid: int | None = 900
    foreground_window: int | None = 900
    allow_activation: bool = True

    window_owned_by_process: bool = True

    def find_window_for_pid(self, pid: int, timeout_seconds: float) -> int | None:
        return self.window_for_pid

    def window_belongs_to_process(self, handle: int, pid: int) -> bool:
        return self.window_owned_by_process

    def activate(self, handle: int) -> None:
        self.activated.append(handle)
        if self.allow_activation:
            self.foreground_window = handle

    def is_foreground(self, handle: int) -> bool:
        return handle == self.foreground_window

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


def make_manager(
    *, brave: Path | None = Path("C:/Apps/brave.exe")
) -> tuple[ApplicationManager, FakeLauncher, FakeWindows, FakeInput]:
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
        manager, _, windows, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)

        await manager.forward_command(Command.NAV_LEFT)

        assert input_controller.commands == [Command.NAV_LEFT]
        assert windows.activated == [900]

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


def test_failed_application_launch_keeps_the_existing_tracked_window_visible() -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager()
        await manager.open(ActiveApp.YOUTUBE)
        launcher.fail_next_launch = True

        with pytest.raises(CommandExecutionError, match="Could not open Microsoft Edge"):
            await manager.open(ActiveApp.NETFLIX)

        assert windows.minimized == []
        assert manager.active_app is ActiveApp.YOUTUBE

    import asyncio

    asyncio.run(scenario())


def test_forwarding_rejects_input_when_the_tracked_window_loses_foreground() -> None:
    async def scenario() -> None:
        manager, _, windows, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        windows.foreground_window = 123
        windows.allow_activation = False

        with pytest.raises(CommandExecutionError, match="Bring the controller-opened application"):
            await manager.forward_command(Command.OK)

        assert input_controller.commands == []

    import asyncio

    asyncio.run(scenario())


def test_forwarding_rejects_input_after_the_tracked_process_exits() -> None:
    async def scenario() -> None:
        manager, launcher, windows, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        launcher.process.exit_code = 0

        with pytest.raises(
            CommandExecutionError, match="controller-managed application window is not available"
        ):
            await manager.forward_command(Command.OK)

        assert input_controller.commands == []
        assert windows.activated == []

    import asyncio

    asyncio.run(scenario())


def test_forwarding_rejects_a_reused_tracked_window_handle() -> None:
    async def scenario() -> None:
        manager, _, windows, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        windows.window_owned_by_process = False

        with pytest.raises(
            CommandExecutionError, match="controller-managed application window is not available"
        ):
            await manager.forward_command(Command.OK)

        assert input_controller.commands == []
        assert windows.activated == []

    import asyncio

    asyncio.run(scenario())


def test_home_does_not_minimize_a_reused_tracked_window_handle() -> None:
    async def scenario() -> None:
        manager, _, windows, _ = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        windows.window_owned_by_process = False

        await manager.return_home()

        assert windows.minimized == []
        assert windows.brought_launcher_forward == 1

    import asyncio

    asyncio.run(scenario())
