from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from app.applications import manager as manager_module
from app.applications.manager import ApplicationManager
from app.applications.netflix_page import NetflixAction
from app.commands.ports import CommandExecutionError
from app.config import ApplicationSettings, Settings, UrlSettings
from app.protocol import Command
from app.state import ActiveApp


@dataclass
class FakeProcess:
    pid: int = 123
    terminated: bool = False
    killed: bool = False
    exit_code: int | None = None
    terminate_failures_remaining: int = 0
    wait_timeouts_remaining: int = 0

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        if self.terminate_failures_remaining > 0:
            self.terminate_failures_remaining -= 1
            raise OSError("terminate failed")
        self.terminated = True

    def wait(self, timeout: float) -> None:
        if self.wait_timeouts_remaining > 0:
            self.wait_timeouts_remaining -= 1
            raise subprocess.TimeoutExpired("fake-browser", timeout)
        self.exit_code = 0

    def kill(self) -> None:
        self.killed = True
        return None

@dataclass
class FakeLauncher:
    calls: list[list[str]] = field(default_factory=list)
    process: FakeProcess = field(default_factory=FakeProcess)
    processes: list[FakeProcess] = field(default_factory=list)
    fail_next_launch: bool = False

    def __call__(self, arguments: list[str]) -> FakeProcess:
        self.calls.append(arguments)
        if self.fail_next_launch:
            self.fail_next_launch = False
            raise OSError("launch failed")
        process = FakeProcess(
            pid=123 + len(self.processes),
            terminate_failures_remaining=self.process.terminate_failures_remaining,
            wait_timeouts_remaining=self.process.wait_timeouts_remaining,
        )
        self.process.terminate_failures_remaining = 0
        self.process.wait_timeouts_remaining = 0
        self.process = process
        self.processes.append(process)
        return process




@dataclass
class FakeWindows:
    minimized: list[int] = field(default_factory=list)
    maximized: list[int] = field(default_factory=list)
    activated: list[int] = field(default_factory=list)
    brought_launcher_forward: int = 0
    closed_launcher: int = 0
    closed_windows: list[int] = field(default_factory=list)
    titled_window: int | None = None
    window_for_pid: int | None = 900
    foreground_window: int | None = 900
    allow_activation: bool = True
    window_owned_by_process: bool = True
    ownership_results: list[bool] = field(default_factory=list)

    def find_window_for_pid(self, pid: int, timeout_seconds: float) -> int | None:
        return self.window_for_pid

    def window_belongs_to_process(self, handle: int, pid: int) -> bool:
        if self.ownership_results:
            return self.ownership_results.pop(0)
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

    def close_launcher(self) -> None:
        self.closed_launcher += 1

    def focus_window_with_title(self, title_fragment: str) -> int | None:
        if self.titled_window is None:
            return None
        self.activate(self.titled_window)
        return self.titled_window

    def close_window(self, handle: int) -> None:
        self.closed_windows.append(handle)


@dataclass
class FakeInput:
    commands: list[Command] = field(default_factory=list)
    browser_backs: int = 0

    def send_command(self, command: Command) -> None:
        self.commands.append(command)

    def send_browser_back(self) -> None:
        self.browser_backs += 1


@dataclass
class FakeNetflixPageController:
    actions: list[tuple[int, NetflixAction]] = field(default_factory=list)
    attempts: list[tuple[int, NetflixAction]] = field(default_factory=list)
    typed: list[tuple[int, str]] = field(default_factory=list)
    failure: CommandExecutionError | None = None
    failures_remaining: int | None = None
    block_execute: bool = False
    cancellations: int = 0

    async def execute(self, port: int, action: NetflixAction) -> None:
        self.attempts.append((port, action))
        if self.block_execute:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancellations += 1
                raise
        if self.failure is not None and (
            self.failures_remaining is None or self.failures_remaining > 0
        ):
            if self.failures_remaining is not None:
                self.failures_remaining -= 1
            raise self.failure
        self.actions.append((port, action))

    async def type_text(self, port: int, text: str) -> None:
        if self.failure is not None:
            raise self.failure
        self.typed.append((port, text))



@dataclass
class FakeAdFilter:
    ports: list[int] = field(default_factory=list)

    async def attach(self, port: int) -> None:
        self.ports.append(port)


def _ready_adblock(tmp_path: Path) -> Path:
    adblock = tmp_path / "adblock"
    adblock.mkdir()
    (adblock / "manifest.json").write_text("{}", encoding="utf-8")
    youtube = tmp_path / "adblock-youtube"
    youtube.mkdir()
    (youtube / "manifest.json").write_text("{}", encoding="utf-8")
    return adblock


def make_manager(
    *,
    chrome: Path | None = Path("C:/Apps/chrome.exe"),
    adblock_dir: Path | None = None,
    adblock_youtube_dir: Path | None = None,
    netflix_page: FakeNetflixPageController | None = None,
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
        executable_paths={
            "chrome": chrome,
            "edge": Path("C:/Apps/msedge.exe"),
            "brave": None,
            "browser": None,
        },
        process_launcher=launcher,
        windows=windows,
        input_controller=input_controller,
        adblock_dir=adblock_dir,
        adblock_youtube_dir=adblock_youtube_dir,
        adfilter=FakeAdFilter(),
        netflix_page=netflix_page or FakeNetflixPageController(),
        debug_port=9333,
        netflix_debug_port=9444,
    )
    return manager, launcher, windows, input_controller


def test_youtube_uses_isolated_chrome_fullscreen_and_ad_filter(tmp_path: Path) -> None:
    manager, launcher, windows, _ = make_manager()
    asyncio.run(manager.open(ActiveApp.YOUTUBE))
    argv = launcher.calls[0]
    assert argv[0].endswith("chrome.exe")
    assert "--start-fullscreen" in argv
    assert "--kiosk" not in argv
    assert "--load-extension" not in " ".join(argv)
    assert "--disable-extensions-except" not in " ".join(argv)
    assert any(part.startswith("--user-data-dir=") and "chrome-tv-profile" in part for part in argv)
    assert "--remote-debugging-address=127.0.0.1" in argv
    assert "--remote-debugging-port=9333" in argv
    assert argv[-1] == "https://www.youtube.com/tv"
    assert any(part.startswith("--user-agent=") and "SMART-TV" in part for part in argv)
    assert "--hide-crash-restore-bubble" in argv
    assert "--noerrdialogs" in argv
    assert manager._adfilter.ports == [9333]


def test_netflix_opens_desktop_chrome_fullscreen() -> None:
    manager, launcher, windows, _ = make_manager()
    asyncio.run(manager.open(ActiveApp.NETFLIX))
    argv = launcher.calls[0]
    assert argv[0].endswith("chrome.exe")
    assert argv[-1] == "https://www.netflix.com/"
    assert "--start-fullscreen" in argv
    assert "--app=" not in " ".join(argv)
    assert "--new-window" not in argv
    assert "--start-maximized" not in argv
    assert any(
        part.startswith("--user-data-dir=") and "chrome-netflix-profile" in part
        for part in argv
    )
    assert "--remote-debugging-address=127.0.0.1" in argv
    assert "--remote-debugging-port=9444" in argv
    assert "--load-extension" not in " ".join(argv)
    assert "--disable-extensions" in argv
    assert "--hide-crash-restore-bubble" in argv
    assert manager._adfilter.ports == []
    assert manager._netflix_page.actions == [(9444, NetflixAction.FOCUS_PRIMARY)]


def test_netflix_text_and_tab_use_page_controller_without_windows_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        manager, _, _, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        await manager.type_text("user@example.com")
        await manager.forward_command(Command.TAB)
        assert manager._netflix_page.typed == [(9444, "user@example.com")]
        assert manager._netflix_page.actions == [
            (9444, NetflixAction.FOCUS_PRIMARY),
            (9444, NetflixAction.FOCUS_NEXT),
        ]
        assert input_controller.commands == []
        assert input_controller.browser_backs == 0
        assert "user@example.com" not in caplog.text

    asyncio.run(scenario())



def test_mark_chrome_profile_clean_exit_clears_crash_state(tmp_path: Path) -> None:
    from app.applications.manager import mark_chrome_profile_clean_exit

    prefs = tmp_path / "Default" / "Preferences"
    prefs.parent.mkdir(parents=True)
    prefs.write_text(
        json.dumps({"profile": {"exit_type": "Crashed", "exited_cleanly": False}}),
        encoding="utf-8",
    )
    mark_chrome_profile_clean_exit(tmp_path)
    data = json.loads(prefs.read_text(encoding="utf-8"))
    assert data["profile"]["exit_type"] == "Normal"
    assert data["profile"]["exited_cleanly"] is True



def test_opening_netflix_twice_reuses_the_same_window() -> None:
    manager, launcher, windows, _ = make_manager()
    asyncio.run(manager.open(ActiveApp.NETFLIX))
    asyncio.run(manager.open(ActiveApp.NETFLIX))
    assert len(launcher.calls) == 1
    assert windows.activated == [900]
    assert windows.maximized[-1] == 900
    assert manager.active_app is ActiveApp.NETFLIX
    assert manager._netflix_page.actions == [
        (9444, NetflixAction.FOCUS_PRIMARY),
        (9444, NetflixAction.FOCUS_PRIMARY),
    ]


def test_home_then_netflix_restores_existing_app() -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        await manager.return_home()
        await manager.open(ActiveApp.NETFLIX)
        assert len(launcher.calls) == 1
        assert manager.active_app is ActiveApp.NETFLIX
        assert 900 in windows.activated

    asyncio.run(scenario())


def test_missing_chrome_returns_chrome_not_found() -> None:
    with pytest.raises(CommandExecutionError) as error:
        asyncio.run(make_manager(chrome=None)[0].open(ActiveApp.YOUTUBE))
    assert error.value.code == "chrome_not_found"


def test_search_youtube_opens_results_url() -> None:
    manager, launcher, _, _ = make_manager()
    asyncio.run(manager.search_youtube("cat videos"))
    argv = launcher.calls[0]
    assert argv[0].endswith("chrome.exe")
    assert "--start-fullscreen" in argv
    assert argv[-1] == "https://www.youtube.com/tv#/search?q=cat+videos"
    assert manager.active_app is ActiveApp.YOUTUBE


def test_search_youtube_replaces_an_existing_youtube_window() -> None:
    manager, launcher, _, _ = make_manager()
    asyncio.run(manager.open(ActiveApp.YOUTUBE))
    asyncio.run(manager.search_youtube("cat videos"))
    assert len(launcher.calls) == 2
    assert launcher.calls[1][-1] == "https://www.youtube.com/tv#/search?q=cat+videos"
    assert manager.active_app is ActiveApp.YOUTUBE

def test_opening_youtube_twice_replaces_the_first_window() -> None:
    manager, launcher, windows, _ = make_manager()
    asyncio.run(manager.open(ActiveApp.YOUTUBE))
    first = launcher.processes[0]
    asyncio.run(manager.open(ActiveApp.YOUTUBE))
    assert first.poll() is not None
    assert windows.closed_windows == [900]
    assert len(launcher.calls) == 2
    assert manager.active_app is ActiveApp.YOUTUBE


def test_opening_netflix_closes_playing_youtube() -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager()
        await manager.open(ActiveApp.YOUTUBE)
        youtube = launcher.processes[0]
        await manager.open(ActiveApp.NETFLIX)
        assert youtube.poll() is not None
        assert windows.closed_windows == [900]
        assert manager.active_app is ActiveApp.NETFLIX
        assert launcher.calls[1][-1] == "https://www.netflix.com/"
        assert "--app=" not in " ".join(launcher.calls[1])

    asyncio.run(scenario())



def test_home_closes_youtube_but_keeps_netflix() -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        netflix = launcher.processes[0]
        await manager.open(ActiveApp.YOUTUBE)
        youtube = launcher.processes[1]
        await manager.return_home()
        assert youtube.poll() is not None
        assert netflix.poll() is None
        assert manager.active_app is ActiveApp.LAUNCHER
        await manager.open(ActiveApp.NETFLIX)
        assert len(launcher.calls) == 2
        assert manager.active_app is ActiveApp.NETFLIX

    asyncio.run(scenario())





def test_leave_to_desktop_closes_youtube_and_launcher(tmp_path: Path) -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager(adblock_dir=_ready_adblock(tmp_path))
        await manager.open(ActiveApp.YOUTUBE)
        await manager.leave_to_desktop()
        assert launcher.process.poll() is not None
        assert windows.closed_windows == [900]
        assert windows.closed_launcher == 1
        assert manager.active_app is ActiveApp.LAUNCHER

    asyncio.run(scenario())




def test_open_news_opens_kiosk_chrome_with_live_url(tmp_path: Path) -> None:
    adblock = _ready_adblock(tmp_path)
    manager, launcher, _, _ = make_manager(adblock_dir=adblock)
    news_url = "https://www.youtube.com/watch?v=live_stream_id"
    asyncio.run(manager.open_news(news_url))
    argv = launcher.calls[0]
    assert argv[0].endswith("chrome.exe")
    assert "--start-fullscreen" in argv
    assert argv[-1] == news_url
    assert manager.active_app is ActiveApp.NEWS





def test_home_minimizes_only_the_tracked_window_and_restores_launcher() -> None:
    async def scenario() -> None:
        manager, _, windows, _ = make_manager()
        await manager.open(ActiveApp.NETFLIX)

        await manager.return_home()

        assert windows.minimized == [900]
        assert windows.brought_launcher_forward == 1
        assert manager.active_app is ActiveApp.LAUNCHER

    asyncio.run(scenario())
@pytest.mark.parametrize(
    ("command", "action"),
    [
        (Command.NAV_UP, NetflixAction.NAV_UP),
        (Command.NAV_DOWN, NetflixAction.NAV_DOWN),
        (Command.NAV_LEFT, NetflixAction.NAV_LEFT),
        (Command.NAV_RIGHT, NetflixAction.NAV_RIGHT),
        (Command.OK, NetflixAction.OK),
        (Command.BACK, NetflixAction.BACK),
        (Command.PLAY_PAUSE, NetflixAction.PLAY_PAUSE),
        (Command.TAB, NetflixAction.FOCUS_NEXT),
    ],
)
def test_netflix_page_commands_use_controller_without_windows_input(
    command: Command,
    action: NetflixAction,
) -> None:
    async def scenario() -> None:
        manager, _, windows, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        manager._netflix_page.actions.clear()

        await manager.forward_command(command)

        assert manager._netflix_page.actions == [(9444, action)]
        assert input_controller.commands == []
        assert input_controller.browser_backs == 0
        assert windows.activated == [900]

    asyncio.run(scenario())


def test_netflix_action_mapping_is_fixed_and_complete() -> None:
    assert manager_module.NETFLIX_ACTIONS == {
        Command.NAV_UP: NetflixAction.NAV_UP,
        Command.NAV_DOWN: NetflixAction.NAV_DOWN,
        Command.NAV_LEFT: NetflixAction.NAV_LEFT,
        Command.NAV_RIGHT: NetflixAction.NAV_RIGHT,
        Command.OK: NetflixAction.OK,
        Command.BACK: NetflixAction.BACK,
        Command.PLAY_PAUSE: NetflixAction.PLAY_PAUSE,
        Command.TAB: NetflixAction.FOCUS_NEXT,
    }


def test_netflix_controller_failure_never_falls_back_to_windows_input() -> None:
    async def scenario() -> None:
        page = FakeNetflixPageController()
        manager, _, _, input_controller = make_manager(netflix_page=page)
        await manager.open(ActiveApp.NETFLIX)
        page.actions.clear()
        page.failure = CommandExecutionError(
            "netflix_controller_unavailable",
            "無法載入 Netflix 遙控控制，請稍後再試。",
        )

        with pytest.raises(CommandExecutionError) as caught:
            await manager.forward_command(Command.OK)

        assert caught.value is page.failure
        assert page.actions == []
        assert input_controller.commands == []
        assert input_controller.browser_backs == 0
        assert manager.active_app is ActiveApp.NETFLIX

    asyncio.run(scenario())


def test_browser_back_still_uses_alt_left_path() -> None:
    async def scenario() -> None:
        manager, _, _, input_controller = make_manager()
        await manager.open(ActiveApp.BROWSER)

        await manager.forward_command(Command.BACK)

        assert input_controller.browser_backs == 1
        assert input_controller.commands == []
        assert manager._netflix_page.actions == []

    asyncio.run(scenario())


def test_youtube_and_news_commands_still_use_windows_input() -> None:
    async def scenario() -> None:
        manager, _, _, input_controller = make_manager()
        await manager.open(ActiveApp.YOUTUBE)
        await manager.forward_command(Command.BACK)
        await manager.open_news("https://www.youtube.com/@dwnews/live")
        await manager.forward_command(Command.PLAY_PAUSE)

        assert input_controller.commands == [Command.BACK, Command.PLAY_PAUSE]
        assert input_controller.browser_backs == 0
        assert manager._netflix_page.actions == []

    asyncio.run(scenario())


def test_netflix_initial_focus_failure_rolls_back_only_new_owned_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async def no_delay(_seconds: float) -> None:
            return None

        monkeypatch.setattr(manager_module, "_NETFLIX_INITIALIZATION_ATTEMPTS", 2)
        monkeypatch.setattr(manager_module.asyncio, "sleep", no_delay)
        failure = CommandExecutionError(
            "netflix_controller_unavailable",
            "無法載入 Netflix 遙控控制，請稍後再試。",
        )
        page = FakeNetflixPageController(failure=failure)
        manager, launcher, windows, input_controller = make_manager(netflix_page=page)

        with pytest.raises(CommandExecutionError) as caught:
            await manager.open(ActiveApp.NETFLIX)

        assert caught.value is failure
        assert launcher.process.poll() is not None
        assert windows.closed_windows == [900]
        assert windows.brought_launcher_forward == 1
        assert manager.active_app is ActiveApp.LAUNCHER
        assert input_controller.commands == []
        assert input_controller.browser_backs == 0

    asyncio.run(scenario())


def test_reused_netflix_initial_focus_failure_reminimizes_without_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async def no_delay(_seconds: float) -> None:
            return None

        monkeypatch.setattr(manager_module, "_NETFLIX_INITIALIZATION_ATTEMPTS", 2)
        monkeypatch.setattr(manager_module.asyncio, "sleep", no_delay)
        page = FakeNetflixPageController()
        manager, launcher, windows, input_controller = make_manager(netflix_page=page)
        await manager.open(ActiveApp.NETFLIX)
        await manager.return_home()
        page.failure = CommandExecutionError(
            "netflix_controller_unavailable",
            "無法載入 Netflix 遙控控制，請稍後再試。",
        )

        with pytest.raises(CommandExecutionError) as caught:
            await manager.open(ActiveApp.NETFLIX)

        assert caught.value is page.failure
        assert launcher.process.poll() is None
        assert windows.closed_windows == []
        assert windows.minimized == [900, 900]
        assert windows.brought_launcher_forward == 2
        assert manager.active_app is ActiveApp.LAUNCHER
        assert input_controller.commands == []

    asyncio.run(scenario())




def test_new_netflix_initialization_has_a_wall_clock_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(
            manager_module,
            "_NETFLIX_INITIALIZATION_TIMEOUT_SECONDS",
            0.01,
            raising=False,
        )
        page = FakeNetflixPageController(block_execute=True)
        manager, launcher, windows, _ = make_manager(netflix_page=page)
        started = asyncio.get_running_loop().time()

        with pytest.raises(CommandExecutionError) as caught:
            await asyncio.wait_for(manager.open(ActiveApp.NETFLIX), timeout=0.5)

        assert asyncio.get_running_loop().time() - started < 0.5
        assert caught.value.code == "netflix_controller_unavailable"
        assert caught.value.message == "無法載入 Netflix 遙控控制，請稍後再試。"
        assert page.attempts == [(9444, NetflixAction.FOCUS_PRIMARY)]
        assert page.cancellations == 1
        assert launcher.process.poll() is not None
        assert windows.closed_windows == [900]
        assert windows.brought_launcher_forward == 1
        assert manager.active_app is ActiveApp.LAUNCHER

    asyncio.run(scenario())


def test_reused_netflix_initialization_timeout_reminimizes_without_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(
            manager_module,
            "_NETFLIX_INITIALIZATION_TIMEOUT_SECONDS",
            0.01,
            raising=False,
        )
        page = FakeNetflixPageController()
        manager, launcher, windows, _ = make_manager(netflix_page=page)
        await manager.open(ActiveApp.NETFLIX)
        await manager.return_home()
        page.attempts.clear()
        page.block_execute = True
        started = asyncio.get_running_loop().time()

        with pytest.raises(CommandExecutionError) as caught:
            await asyncio.wait_for(manager.open(ActiveApp.NETFLIX), timeout=0.5)

        assert asyncio.get_running_loop().time() - started < 0.5
        assert caught.value.code == "netflix_controller_unavailable"
        assert caught.value.message == "無法載入 Netflix 遙控控制，請稍後再試。"
        assert page.attempts == [(9444, NetflixAction.FOCUS_PRIMARY)]
        assert page.cancellations == 1
        assert launcher.process.poll() is None
        assert windows.closed_windows == []
        assert windows.minimized == [900, 900]
        assert windows.brought_launcher_forward == 2
        assert manager.active_app is ActiveApp.LAUNCHER

    asyncio.run(scenario())


def test_netflix_initial_focus_retries_until_page_dom_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async def no_delay(_seconds: float) -> None:
            return None

        monkeypatch.setattr(manager_module, "_NETFLIX_INITIALIZATION_ATTEMPTS", 3)
        monkeypatch.setattr(manager_module.asyncio, "sleep", no_delay)
        page = FakeNetflixPageController(
            failure=CommandExecutionError(
                "netflix_focus_unavailable",
                "找不到可操作的 Netflix 項目，請稍後再試。",
            ),
            failures_remaining=1,
        )
        manager, launcher, windows, _ = make_manager(netflix_page=page)

        await manager.open(ActiveApp.NETFLIX)

        assert page.attempts == [
            (9444, NetflixAction.FOCUS_PRIMARY),
            (9444, NetflixAction.FOCUS_PRIMARY),
        ]
        assert page.actions == [(9444, NetflixAction.FOCUS_PRIMARY)]
        assert launcher.process.poll() is None
        assert windows.closed_windows == []
        assert manager.active_app is ActiveApp.NETFLIX

    asyncio.run(scenario())

def test_shutdown_terminates_only_the_child_started_by_controller() -> None:
    async def scenario() -> None:
        manager, launcher, _, _ = make_manager()
        await manager.open(ActiveApp.NETFLIX)

        await manager.shutdown()

        assert launcher.process.poll() is not None

    import asyncio

    asyncio.run(scenario())


def test_failed_application_launch_keeps_the_existing_tracked_window_visible() -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        launcher.fail_next_launch = True

        with pytest.raises(CommandExecutionError, match="無法開啟已設定的瀏覽器"):
            await manager.open(ActiveApp.BROWSER)

        assert windows.minimized == []
        assert manager.active_app is ActiveApp.NETFLIX

    import asyncio

    asyncio.run(scenario())


@pytest.mark.parametrize("window_handle,window_owned", [(None, True), (900, False)])
def test_open_rejects_an_unowned_or_missing_browser_window(
    tmp_path: Path,
    window_handle: int | None,
    window_owned: bool,
) -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager(adblock_dir=_ready_adblock(tmp_path))
        windows.window_for_pid = window_handle
        windows.window_owned_by_process = window_owned

        with pytest.raises(CommandExecutionError) as caught:
            await manager.open(ActiveApp.YOUTUBE)

        assert caught.value.code == "application_window_unavailable"
        assert "請先關閉現有的YouTube視窗" in caught.value.message
        assert launcher.process.terminated
        assert manager.active_app is ActiveApp.LAUNCHER
        assert windows.maximized == []

    asyncio.run(scenario())


def test_unowned_browser_uses_kill_fallback_after_terminate_timeout(tmp_path: Path) -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager(adblock_dir=_ready_adblock(tmp_path))
        launcher.process.wait_timeouts_remaining = 1
        windows.window_for_pid = None

        with pytest.raises(CommandExecutionError):
            await manager.open(ActiveApp.YOUTUBE)

        assert launcher.process.terminated
        assert launcher.process.killed
        assert launcher.process.exit_code == 0

    asyncio.run(scenario())


def test_window_that_disappears_while_maximizing_is_not_committed_as_active(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager(adblock_dir=_ready_adblock(tmp_path))
        windows.ownership_results = [True, False]

        with pytest.raises(CommandExecutionError) as caught:
            await manager.open(ActiveApp.YOUTUBE)

        assert caught.value.code == "application_window_unavailable"
        assert manager.active_app is ActiveApp.LAUNCHER
        assert windows.maximized == [900]
        assert launcher.process.terminated

    asyncio.run(scenario())


def test_failed_orphan_cleanup_is_retried_during_shutdown(tmp_path: Path) -> None:
    async def scenario() -> None:
        manager, launcher, windows, _ = make_manager(adblock_dir=_ready_adblock(tmp_path))
        launcher.process.terminate_failures_remaining = 1
        windows.window_for_pid = None

        with pytest.raises(CommandExecutionError):
            await manager.open(ActiveApp.YOUTUBE)
        assert not launcher.process.terminated

        await manager.shutdown()

        assert launcher.process.terminated
        assert launcher.process.exit_code == 0

    asyncio.run(scenario())


def test_windows_input_rejects_a_tracked_window_that_loses_foreground() -> None:
    async def scenario() -> None:
        manager, _, windows, input_controller = make_manager()
        await manager.open(ActiveApp.BROWSER)
        windows.foreground_window = 123
        windows.allow_activation = False

        with pytest.raises(CommandExecutionError, match="請先把控制器開啟的應用程式"):
            await manager.forward_command(Command.OK)

        assert input_controller.commands == []

    asyncio.run(scenario())


def test_netflix_cdp_accepts_an_owned_window_when_foreground_activation_is_denied() -> None:
    async def scenario() -> None:
        manager, _, windows, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        manager._netflix_page.actions.clear()
        windows.foreground_window = 123
        windows.allow_activation = False

        await manager.forward_command(Command.TAB)

        assert manager._netflix_page.actions == [(9444, NetflixAction.FOCUS_NEXT)]
        assert input_controller.commands == []

    asyncio.run(scenario())


def test_forwarding_rejects_input_after_the_tracked_process_exits() -> None:
    async def scenario() -> None:
        manager, launcher, windows, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        launcher.process.exit_code = 0

        with pytest.raises(
            CommandExecutionError, match="控制器管理的應用程式視窗目前無法接受遙控輸入"
        ):
            await manager.forward_command(Command.OK)

        assert input_controller.commands == []
        assert windows.activated == []

    import asyncio

    asyncio.run(scenario())


def test_forwarding_rebinds_a_replacement_window_from_the_same_owned_process() -> None:
    async def scenario() -> None:
        manager, _, windows, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        manager._netflix_page.actions.clear()
        windows.window_for_pid = 901
        windows.ownership_results = [False, True, True]

        await manager.forward_command(Command.TAB)

        assert manager._netflix_page.actions == [(9444, NetflixAction.FOCUS_NEXT)]
        assert windows.activated == [901]
        assert input_controller.commands == []

    asyncio.run(scenario())


def test_forwarding_rejects_a_reused_tracked_window_handle() -> None:
    async def scenario() -> None:
        manager, _, windows, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        windows.window_owned_by_process = False

        with pytest.raises(
            CommandExecutionError, match="控制器管理的應用程式視窗目前無法接受遙控輸入"
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


def test_forwarding_accepts_input_for_news_target(tmp_path: Path) -> None:
    async def scenario() -> None:
        manager, _, windows, input_controller = make_manager(adblock_dir=_ready_adblock(tmp_path))
        await manager.open_news("https://www.youtube.com/watch?v=live123")

        await manager.forward_command(Command.NAV_DOWN)

        assert input_controller.commands == [Command.NAV_DOWN]
        assert windows.activated == [900]

    asyncio.run(scenario())
