from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.commands.bus import CommandBus
from app.commands.ports import CommandExecutionError
from app.player.channels import Channel
from app.protocol import (
    Command,
    PointerAction,
    PointerActionMessage,
    SearchVideoMessage,
    TextInputMessage,
)
from app.state import ActiveApp, ControllerState, StateStore


@dataclass
class FakeApplications:
    opened: list[ActiveApp] = field(default_factory=list)
    opened_news: list[str] = field(default_factory=list)
    searches: list[str] = field(default_factory=list)
    home_calls: int = 0
    desktop_calls: int = 0
    forwarded: list[Command] = field(default_factory=list)
    input_targets: list[ActiveApp] = field(default_factory=list)
    typed: list[str] = field(default_factory=list)
    failure: CommandExecutionError | None = None

    async def open(self, app: ActiveApp) -> None:
        self.opened.append(app)
    async def open_news(self, url: str) -> None:
        self.opened_news.append(url)

    async def search_youtube(self, query: str) -> None:
        self.searches.append(query)

    async def return_home(self) -> None:
        self.home_calls += 1

    async def leave_to_desktop(self) -> None:
        self.desktop_calls += 1

    async def forward_command(self, command: Command) -> None:
        if self.failure is not None:
            raise self.failure
        self.forwarded.append(command)

    async def type_text(self, text: str) -> None:
        if self.failure is not None:
            raise self.failure
        self.typed.append(text)

    def require_input_target(self, app: ActiveApp) -> None:
        self.input_targets.append(app)



@dataclass
class BlockingApplications(FakeApplications):
    open_started: asyncio.Event = field(default_factory=asyncio.Event)
    release_open: asyncio.Event = field(default_factory=asyncio.Event)
    open_calls: int = 0

    async def open(self, app: ActiveApp) -> None:
        self.open_calls += 1
        if self.open_calls == 1:
            self.open_started.set()
            await self.release_open.wait()
        self.opened.append(app)


class RejectingApplications(FakeApplications):
    async def open(self, app: ActiveApp) -> None:
        raise CommandExecutionError("application_not_found", "Configured browser is unavailable.")


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

@dataclass
class FakeNews:
    channels: list[Channel] = field(
        default_factory=lambda: [
            Channel(
                id="dw-news",
                number=1,
                name="DW News",
                url="https://www.youtube.com/@dwnews/live",
            ),
            Channel(
                id="aljazeera-english",
                number=2,
                name="Al Jazeera English",
                url="https://www.youtube.com/@aljazeeraenglish/live",
            ),
        ]
    )
    current_index: int = 0

    @property
    def current(self) -> Channel:
        return self.channels[self.current_index]

    def move(self, direction: int) -> Channel:
        self.current_index = (self.current_index + direction) % len(self.channels)
        return self.current



def make_bus(
    news: FakeNews | None = None,
) -> tuple[CommandBus, FakeApplications, FakePlayer, FakeInput]:
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
        news=news or FakeNews(),
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

def test_back_on_launcher_does_not_leave_desktop() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()

        result = await bus.dispatch_command(Command.BACK)

        assert result.success
        assert applications.desktop_calls == 0
        assert applications.forwarded == []
        assert result.state.active_app is ActiveApp.LAUNCHER

    asyncio.run(scenario())


def test_back_from_youtube_forwards_escape() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_YOUTUBE)

        result = await bus.dispatch_command(Command.BACK)

        assert result.success
        assert applications.desktop_calls == 0
        assert applications.forwarded == [Command.BACK]
        assert result.state.active_app is ActiveApp.YOUTUBE

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


def test_opening_a_browser_from_live_tv_stops_mpv_before_home() -> None:
    async def scenario() -> None:
        bus, applications, player, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_LIVE_TV)

        opened = await bus.dispatch_command(Command.OPEN_BROWSER)
        returned_home = await bus.dispatch_command(Command.HOME)

        assert opened.success
        assert opened.state.active_app is ActiveApp.BROWSER
        assert applications.opened == [ActiveApp.BROWSER]
        assert player.closed == 1
        assert returned_home.success
        assert returned_home.state.active_app is ActiveApp.LAUNCHER
        assert player.closed == 1

    asyncio.run(scenario())


def test_failed_application_transition_from_live_tv_returns_to_launcher() -> None:
    async def scenario() -> None:
        applications = RejectingApplications()
        player = FakePlayer()
        bus = CommandBus(
            StateStore(ControllerState()),
            applications=applications,
            player=player,
            volume=FakeVolume(),
            input_controller=FakeInput(),
            power=FakePower(),
            news=FakeNews(),
        )
        await bus.dispatch_command(Command.OPEN_LIVE_TV)

        result = await bus.dispatch_command(Command.OPEN_BROWSER)

        assert not result.success
        assert result.error_code == "application_not_found"
        assert result.state.active_app is ActiveApp.LAUNCHER
        assert result.state.channel_number is None
        assert result.state.channel_name is None
        assert applications.home_calls == 1
        assert player.closed == 1

    asyncio.run(scenario())


def test_pointer_and_text_actions_use_bounded_protocol_messages() -> None:
    async def scenario() -> None:
        bus, applications, _, input_controller = make_bus()
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

        await bus.dispatch_command(Command.OPEN_BROWSER)

        pointer_result = await bus.dispatch_pointer(pointer)
        text_result = await bus.dispatch_text(text)

        assert pointer_result.success and text_result.success
        assert not pointer_result.state_changed and not text_result.state_changed
        assert input_controller.pointers == [pointer]
        assert input_controller.texts == ["search term"]
        assert applications.input_targets == [ActiveApp.BROWSER, ActiveApp.BROWSER]

    asyncio.run(scenario())


def test_netflix_text_is_typed_into_the_netflix_page() -> None:
    async def scenario() -> None:
        bus, applications, _, input_controller = make_bus()
        await bus.dispatch_command(Command.OPEN_NETFLIX)
        result = await bus.dispatch_text(
            TextInputMessage(
                version=1,
                type="text_input",
                request_id="text-netflix-1",
                text="user@example.com",
            )
        )
        assert result.success
        assert applications.typed == ["user@example.com"]
        assert input_controller.texts == []

    asyncio.run(scenario())


def test_netflix_commands_and_text_use_only_application_port() -> None:
    async def scenario() -> None:
        bus, applications, _, input_controller = make_bus()
        await bus.dispatch_command(Command.OPEN_NETFLIX)
        commands = [
            Command.NAV_UP,
            Command.NAV_DOWN,
            Command.NAV_LEFT,
            Command.NAV_RIGHT,
            Command.OK,
            Command.BACK,
            Command.PLAY_PAUSE,
            Command.TAB,
        ]
        outcomes = [await bus.dispatch_command(command) for command in commands]
        text = await bus.dispatch_text(
            TextInputMessage(
                version=1,
                type="text_input",
                request_id="netflix-text-256",
                text="x" * 256,
            )
        )

        assert all(outcome.success and not outcome.state_changed for outcome in outcomes)
        assert text.success and not text.state_changed
        assert applications.forwarded == commands
        assert applications.typed == ["x" * 256]
        assert input_controller.texts == []

    asyncio.run(scenario())


def test_netflix_error_becomes_failed_ack_without_active_app_change() -> None:
    async def scenario() -> None:
        bus, applications, _, input_controller = make_bus()
        opened = await bus.dispatch_command(Command.OPEN_NETFLIX)
        assert opened.success
        applications.failure = CommandExecutionError(
            "netflix_controller_unavailable",
            "無法載入 Netflix 遙控控制，請稍後再試。",
        )

        command = await bus.dispatch_command(Command.OK)
        text = await bus.dispatch_text(
            TextInputMessage(
                version=1,
                type="text_input",
                request_id="netflix-error-text",
                text="secret",
            )
        )

        for outcome in (command, text):
            assert not outcome.success
            assert outcome.error_code == "netflix_controller_unavailable"
            assert outcome.message == "無法載入 Netflix 遙控控制，請稍後再試。"
            assert outcome.state.active_app is ActiveApp.NETFLIX
            assert outcome.state.error_message == "無法載入 Netflix 遙控控制，請稍後再試。"
        assert input_controller.texts == []

    asyncio.run(scenario())



def test_external_navigation_is_forwarded_without_changing_active_application() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_BROWSER)

        result = await bus.dispatch_command(Command.NAV_DOWN)

        assert result.success
        assert applications.forwarded == [Command.NAV_DOWN]
        assert not result.state_changed
        assert result.state.active_app is ActiveApp.BROWSER

    asyncio.run(scenario())


def test_commands_are_serialized_across_paired_remotes() -> None:
    async def scenario() -> None:
        applications = BlockingApplications()
        bus = CommandBus(
            StateStore(ControllerState()),
            applications=applications,
            player=FakePlayer(),
            volume=FakeVolume(),
            input_controller=FakeInput(),
            power=FakePower(),
            news=FakeNews(),
        )

        first = asyncio.create_task(bus.dispatch_command(Command.OPEN_YOUTUBE))
        await applications.open_started.wait()
        second = asyncio.create_task(bus.dispatch_command(Command.OPEN_NETFLIX))
        await asyncio.sleep(0)
        try:
            assert applications.open_calls == 1
        finally:
            applications.release_open.set()

        first_outcome, second_outcome = await asyncio.gather(first, second)

        assert first_outcome.success and second_outcome.success
        assert applications.opened == [ActiveApp.YOUTUBE, ActiveApp.NETFLIX]
        assert second_outcome.state.active_app is ActiveApp.NETFLIX

    asyncio.run(scenario())


def test_pointer_and_text_require_a_controller_owned_browser_target() -> None:
    async def scenario() -> None:
        bus, applications, _, input_controller = make_bus()
        text = TextInputMessage(
            version=1, type="text_input", request_id="text-1", text="search term"
        )

        rejected = await bus.dispatch_text(text)
        assert not rejected.success
        assert rejected.error_code == "input_target_not_active"
        assert input_controller.texts == []
        assert applications.input_targets == []

        await bus.dispatch_command(Command.OPEN_BROWSER)
        accepted = await bus.dispatch_text(text)

        assert accepted.success
        assert input_controller.texts == ["search term"]
        assert applications.input_targets == [ActiveApp.BROWSER]

    asyncio.run(scenario())


def test_pointer_and_text_wait_for_an_in_progress_application_transition() -> None:
    async def scenario() -> None:
        applications = BlockingApplications()
        input_controller = FakeInput()
        bus = CommandBus(
            StateStore(ControllerState()),
            applications=applications,
            player=FakePlayer(),
            volume=FakeVolume(),
            input_controller=input_controller,
            power=FakePower(),
            news=FakeNews(),
        )
        pointer = PointerActionMessage(
            version=1,
            type="pointer",
            request_id="pointer-1",
            action=PointerAction.MOVE,
            dx=20,
            dy=-10,
        )
        text = TextInputMessage(
            version=1, type="text_input", request_id="text-1", text="search term"
        )

        opening = asyncio.create_task(bus.dispatch_command(Command.OPEN_BROWSER))
        await applications.open_started.wait()
        pointer_task = asyncio.create_task(bus.dispatch_pointer(pointer))
        text_task = asyncio.create_task(bus.dispatch_text(text))
        await asyncio.sleep(0)

        assert input_controller.pointers == []
        assert input_controller.texts == []

        applications.release_open.set()
        opening_result, pointer_result, text_result = await asyncio.gather(
            opening, pointer_task, text_task
        )

        assert opening_result.success and pointer_result.success and text_result.success
        assert input_controller.pointers == [pointer]
        assert input_controller.texts == ["search term"]
        assert applications.input_targets == [ActiveApp.BROWSER, ActiveApp.BROWSER]

    asyncio.run(scenario())

def test_open_news_sets_channel_and_active_app() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()
        outcome = await bus.dispatch_command(Command.OPEN_NEWS)

        assert outcome.success
        assert outcome.state.active_app is ActiveApp.NEWS
        assert outcome.state.channel_number == 1
        assert outcome.state.channel_name == "DW News"
        assert applications.opened_news == ["https://www.youtube.com/@dwnews/live"]

    asyncio.run(scenario())


def test_channel_up_on_news_opens_next_official_url() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_NEWS)
        outcome = await bus.dispatch_command(Command.CHANNEL_UP)

        assert outcome.success
        assert outcome.state.active_app is ActiveApp.NEWS
        assert outcome.state.channel_number == 2
        assert outcome.state.channel_name == "Al Jazeera English"
        assert applications.opened_news == [
            "https://www.youtube.com/@dwnews/live",
            "https://www.youtube.com/@aljazeeraenglish/live",
        ]

    asyncio.run(scenario())


def test_channel_down_on_news_opens_previous_channel() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_NEWS)
        outcome = await bus.dispatch_command(Command.CHANNEL_DOWN)

        assert outcome.success
        assert outcome.state.active_app is ActiveApp.NEWS
        assert outcome.state.channel_number == 2
        assert outcome.state.channel_name == "Al Jazeera English"
        assert applications.opened_news == [
            "https://www.youtube.com/@dwnews/live",
            "https://www.youtube.com/@aljazeeraenglish/live",
        ]

    asyncio.run(scenario())


def test_channel_up_on_youtube_is_rejected() -> None:
    async def scenario() -> None:
        bus, _, _, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_YOUTUBE)
        outcome = await bus.dispatch_command(Command.CHANNEL_UP)

        assert not outcome.success
        assert outcome.error_code == "channel_source_not_active"
        assert outcome.message == "請先開啟新聞或電視再切換頻道。"

    asyncio.run(scenario())


def test_search_video_opens_youtube_results() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()
        message = SearchVideoMessage(
            version=1,
            type="search_video",
            request_id="search-1",
            query="cat videos",
        )
        outcome = await bus.dispatch_search(message)

        assert outcome.success
        assert outcome.state.active_app is ActiveApp.YOUTUBE
        assert outcome.state.channel_number is None
        assert outcome.state.channel_name is None
        assert applications.searches == ["cat videos"]

    asyncio.run(scenario())


def test_open_news_when_live_tv_active_stops_player() -> None:
    async def scenario() -> None:
        bus, applications, player, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_LIVE_TV)
        assert player.opened == 1
        assert player.closed == 0

        outcome = await bus.dispatch_command(Command.OPEN_NEWS)
        assert outcome.success
        assert player.closed == 1
        assert outcome.state.active_app is ActiveApp.NEWS
        assert applications.opened_news == ["https://www.youtube.com/@dwnews/live"]

    asyncio.run(scenario())


def test_search_video_when_live_tv_active_stops_player() -> None:
    async def scenario() -> None:
        bus, applications, player, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_LIVE_TV)
        assert player.opened == 1
        assert player.closed == 0

        message = SearchVideoMessage(
            version=1,
            type="search_video",
            request_id="search-2",
            query="relaxing music",
        )
        outcome = await bus.dispatch_search(message)
        assert outcome.success
        assert player.closed == 1
        assert outcome.state.active_app is ActiveApp.YOUTUBE
        assert applications.searches == ["relaxing music"]

    asyncio.run(scenario())

def test_unavailable_news_raises_news_not_configured_on_open_news() -> None:
    async def scenario() -> None:
        from app.controller import UnavailableNews

        news = UnavailableNews("尚未設定可用的新聞頻道。請更新 config/news.json。")
        bus, applications, _, _ = make_bus(news=news)
        outcome = await bus.dispatch_command(Command.OPEN_NEWS)

        assert not outcome.success
        assert outcome.error_code == "news_not_configured"
        assert outcome.message == "尚未設定可用的新聞頻道。請更新 config/news.json。"
        assert applications.opened_news == []

    asyncio.run(scenario())


def test_external_navigation_forwarded_when_news_active() -> None:
    async def scenario() -> None:
        bus, applications, _, _ = make_bus()
        await bus.dispatch_command(Command.OPEN_NEWS)

        result = await bus.dispatch_command(Command.NAV_DOWN)

        assert result.success
        assert applications.forwarded == [Command.NAV_DOWN]
        assert not result.state_changed
        assert result.state.active_app is ActiveApp.NEWS

    asyncio.run(scenario())


def test_pointer_and_text_accepted_when_news_active() -> None:
    async def scenario() -> None:
        bus, applications, _, input_controller = make_bus()
        pointer = PointerActionMessage(
            version=1,
            type="pointer",
            request_id="pointer-news-1",
            action=PointerAction.MOVE,
            dx=10,
            dy=20,
        )
        text = TextInputMessage(
            version=1,
            type="text_input",
            request_id="text-news-1",
            text="news query",
        )

        await bus.dispatch_command(Command.OPEN_NEWS)

        pointer_result = await bus.dispatch_pointer(pointer)
        text_result = await bus.dispatch_text(text)

        assert pointer_result.success and text_result.success
        assert not pointer_result.state_changed and not text_result.state_changed
        assert input_controller.pointers == [pointer]
        assert input_controller.texts == ["news query"]
        assert applications.input_targets == [ActiveApp.NEWS, ActiveApp.NEWS]

    asyncio.run(scenario())

