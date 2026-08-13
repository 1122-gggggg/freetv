from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.commands.bus import CommandBus
from app.protocol import Command, PointerAction, PointerActionMessage, TextInputMessage
from app.state import ActiveApp, ControllerState, LauncherTile, StateStore


@dataclass
class FakeApplications:
    opened: list[ActiveApp] = field(default_factory=list)
    home_calls: int = 0
    forwarded: list[Command] = field(default_factory=list)

    async def open(self, app: ActiveApp) -> None:
        self.opened.append(app)

    async def return_home(self) -> None:
        self.home_calls += 1

    async def forward_command(self, command: Command) -> None:
        self.forwarded.append(command)


@dataclass
class FakePlayer:
    opened: int = 0
    actions: list[str] = field(default_factory=list)
    channel_number: int = 1
    channel_name: str = "Demo Channel"
    closed: int = 0


    async def open(self) -> tuple[int, str]:
        self.opened += 1
        return self.channel_number, self.channel_name

    async def toggle_pause(self) -> None:
        self.actions.append("toggle_pause")

    async def next(self) -> None:
        self.actions.append("next")

    async def previous(self) -> None:
        self.actions.append("previous")

    async def change_channel(self, direction: int) -> tuple[int, str]:
        self.channel_number += direction
        return self.channel_number, self.channel_name
    async def close(self) -> None:
        self.closed += 1



@dataclass
class FakeVolume:
    level: int = 42
    muted: bool = False

    async def increase(self) -> tuple[int, bool]:
        self.level += 5
        return self.level, self.muted

    async def decrease(self) -> tuple[int, bool]:
        self.level -= 5
        return self.level, self.muted

    async def toggle_mute(self) -> tuple[int, bool]:
        self.muted = not self.muted
        return self.level, self.muted


@dataclass
class FakeInput:
    pointers: list[PointerActionMessage] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)

    async def pointer(self, message: PointerActionMessage) -> None:
        self.pointers.append(message)

    async def text(self, text: str) -> None:
        self.texts.append(text)


@dataclass
class FakePower:
    sleep_calls: int = 0

    async def sleep(self) -> None:
        self.sleep_calls += 1


def make_bus() -> tuple[CommandBus, FakeApplications, FakePlayer, FakeInput]:
    applications = FakeApplications()
    player = FakePlayer()
    input_controller = FakeInput()
    bus = CommandBus(
        StateStore(ControllerState()),
        applications=applications,
        player=player,
        volume=FakeVolume(),
        input_controller=input_controller,
        power=FakePower(),
    )
    return bus, applications, player, input_controller


def test_launcher_navigation_moves_focus_and_ok_launches_selected_tile() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()

        await bus.dispatch_command(Command.NAV_RIGHT)
        state = await bus.dispatch_command(Command.OK)

        assert state.success
        assert applications.opened == [ActiveApp.NETFLIX]
        assert state.state.active_app is ActiveApp.NETFLIX

    asyncio.run(scenario())


def test_home_returns_from_tracked_application_to_launcher() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_YOUTUBE)

        result = await bus.dispatch_command(Command.HOME)

        assert result.success
        assert applications.home_calls == 1
        assert result.state.active_app is ActiveApp.LAUNCHER

    asyncio.run(scenario())


def test_live_tv_channel_commands_publish_selected_channel() -> None:
    async def scenario() -> None:
        bus, _, player, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_LIVE_TV)

        result = await bus.dispatch_command(Command.CHANNEL_UP)

        assert player.opened == 1
        assert result.state.active_app is ActiveApp.LIVE_TV
        assert result.state.channel_number == 2
        assert result.state.channel_name == "Demo Channel"

    asyncio.run(scenario())

def test_home_stops_the_controller_owned_mpv_process() -> None:
    async def scenario() -> None:
        bus, applications, player, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_LIVE_TV)

        result = await bus.dispatch_command(Command.HOME)

        assert result.success
        assert player.closed == 1
        assert applications.home_calls == 1

    asyncio.run(scenario())


def test_pointer_and_text_actions_use_bounded_protocol_messages() -> None:
    async def scenario() -> None:
        bus, _, _, input_controller = make_bus()
        pointer = PointerActionMessage(
            version=1,
            type="pointer",
            request_id="pointer-1",
            action=PointerAction.MOVE,
            dx=20,
            dy=-10,
        )
        text = TextInputMessage(
            version=1,
            type="text_input",
            request_id="text-1",
            text="search term",
        )

        pointer_result = await bus.dispatch_pointer(pointer)
        text_result = await bus.dispatch_text(text)

        assert pointer_result.success and text_result.success
        assert input_controller.pointers == [pointer]
        assert input_controller.texts == ["search term"]

    asyncio.run(scenario())


def test_external_navigation_is_forwarded_without_changing_active_application() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_BROWSER)

        result = await bus.dispatch_command(Command.NAV_DOWN)

        assert result.success
        assert applications.forwarded == [Command.NAV_DOWN]
        assert result.state.active_app is ActiveApp.BROWSER

    asyncio.run(scenario())
