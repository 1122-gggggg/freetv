from __future__ import annotations

import asyncio
import subprocess
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


@dataclass
class FakeInput:
    commands: list[Command] = field(default_factory=list)

    def send_command(self, command: Command) -> None:
        self.commands.append(command)


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
    )
    return manager, launcher, windows, input_controller


def test_youtube_uses_isolated_chrome_kiosk_and_adblock(tmp_path: Path) -> None:
    adblock = _ready_adblock(tmp_path)
    youtube_adblock = tmp_path / "adblock-youtube"
    manager, launcher, windows, _ = make_manager(adblock_dir=adblock)
    asyncio.run(manager.open(ActiveApp.YOUTUBE))
    argv = launcher.calls[0]
    assert argv[0].endswith("chrome.exe")
    assert "--kiosk" in argv
    assert any(part.startswith("--user-data-dir=") and "chrome-tv-profile" in part for part in argv)
    load_extension = next(part for part in argv if part.startswith("--load-extension="))
    disable_except = next(part for part in argv if part.startswith("--disable-extensions-except="))
    loaded = load_extension.removeprefix("--load-extension=").split(",")
    excepted = disable_except.removeprefix("--disable-extensions-except=").split(",")
    assert loaded == [str(adblock), str(youtube_adblock)]
    assert excepted == [str(adblock), str(youtube_adblock)]
    assert any(
        part.startswith("--disable-features=")
        and "DisableLoadExtensionCommandLineSwitch" in part
        for part in argv
    )
    assert "--start-maximized" not in argv
    assert argv[-1] == "https://www.youtube.com/"

def test_netflix_stays_on_edge_without_adblock() -> None:
    manager, launcher, windows, _ = make_manager()
    asyncio.run(manager.open(ActiveApp.NETFLIX))
    assert launcher.calls[0][0].endswith("msedge.exe")
    assert "--start-maximized" in launcher.calls[0]
    assert "--load-extension" not in " ".join(launcher.calls[0])
    assert "chrome-tv-profile" not in " ".join(launcher.calls[0])


def test_missing_chrome_returns_chrome_not_found(tmp_path: Path) -> None:
    adblock = _ready_adblock(tmp_path)
    with pytest.raises(CommandExecutionError) as error:
        asyncio.run(make_manager(chrome=None, adblock_dir=adblock)[0].open(ActiveApp.YOUTUBE))
    assert error.value.code == "chrome_not_found"


def test_missing_adblock_returns_adblock_not_installed() -> None:
    with pytest.raises(CommandExecutionError) as error:
        asyncio.run(make_manager(adblock_dir=Path("C:/missing-adblock"))[0].open(ActiveApp.YOUTUBE))
    assert error.value.code == "adblock_not_installed"


def test_default_adblock_dir_loads_vendor_adblock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adblock = tmp_path / "vendor" / "adblock"
    adblock.mkdir(parents=True)
    (adblock / "manifest.json").write_text("{}", encoding="utf-8")
    youtube_adblock = tmp_path / "vendor" / "adblock-youtube"
    youtube_adblock.mkdir(parents=True)
    (youtube_adblock / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("app.applications.manager.project_root", lambda: tmp_path)
    manager, launcher, _, _ = make_manager()
    asyncio.run(manager.open(ActiveApp.YOUTUBE))
    argv = launcher.calls[0]
    load_extension = next(part for part in argv if part.startswith("--load-extension="))
    assert load_extension == f"--load-extension={adblock},{youtube_adblock}"
    assert any(
        part.startswith("--disable-features=")
        and "DisableLoadExtensionCommandLineSwitch" in part
        for part in argv
    )


def test_missing_default_adblock_dir_returns_adblock_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.applications.manager.project_root", lambda: tmp_path)
    with pytest.raises(CommandExecutionError) as error:
        asyncio.run(make_manager()[0].open(ActiveApp.YOUTUBE))
    assert error.value.code == "adblock_not_installed"


def test_search_youtube_opens_results_url(tmp_path: Path) -> None:
    adblock = _ready_adblock(tmp_path)
    manager, launcher, _, _ = make_manager(adblock_dir=adblock)
    asyncio.run(manager.search_youtube("cat videos"))
    argv = launcher.calls[0]
    assert argv[0].endswith("chrome.exe")
    assert "--kiosk" in argv
    assert argv[-1] == "https://www.youtube.com/results?search_query=cat+videos"
    assert manager.active_app is ActiveApp.YOUTUBE


def test_open_news_opens_kiosk_chrome_with_live_url(tmp_path: Path) -> None:
    adblock = _ready_adblock(tmp_path)
    manager, launcher, _, _ = make_manager(adblock_dir=adblock)
    news_url = "https://www.youtube.com/watch?v=live_stream_id"
    asyncio.run(manager.open_news(news_url))
    argv = launcher.calls[0]
    assert argv[0].endswith("chrome.exe")
    assert "--kiosk" in argv
    assert argv[-1] == news_url
    assert manager.active_app is ActiveApp.NEWS


def test_missing_youtube_adblock_returns_adblock_not_installed(tmp_path: Path) -> None:
    adblock = tmp_path / "adblock"
    adblock.mkdir()
    (adblock / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CommandExecutionError) as error:
        asyncio.run(make_manager(adblock_dir=adblock)[0].open(ActiveApp.YOUTUBE))
    assert error.value.code == "adblock_not_installed"


def test_home_minimizes_only_the_tracked_window_and_restores_launcher() -> None:
    async def scenario() -> None:
        manager, _, windows, _ = make_manager()
        await manager.open(ActiveApp.NETFLIX)

        await manager.return_home()

        assert windows.minimized == [900]
        assert windows.brought_launcher_forward == 1
        assert manager.active_app is ActiveApp.LAUNCHER

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
        await manager.open(ActiveApp.NETFLIX)

        await manager.shutdown()

        assert launcher.process.terminated

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


def test_forwarding_rejects_input_when_the_tracked_window_loses_foreground() -> None:
    async def scenario() -> None:
        manager, _, windows, input_controller = make_manager()
        await manager.open(ActiveApp.NETFLIX)
        windows.foreground_window = 123
        windows.allow_activation = False

        with pytest.raises(CommandExecutionError, match="請先把控制器開啟的應用程式"):
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
            CommandExecutionError, match="控制器管理的應用程式視窗目前無法接受遙控輸入"
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
