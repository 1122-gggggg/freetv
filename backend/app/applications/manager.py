from __future__ import annotations

import asyncio
import logging
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus

from app.commands.ports import CommandExecutionError
from app.config import Settings, project_root
from app.logging import log_event
from app.protocol import Command
from app.state import ActiveApp

class ChildProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float) -> object: ...


class WindowController(Protocol):
    def find_window_for_pid(self, pid: int, timeout_seconds: float) -> int | None: ...
    def window_belongs_to_process(self, handle: int, pid: int) -> bool: ...
    def minimize(self, handle: int) -> None: ...
    def maximize(self, handle: int) -> None: ...
    def activate(self, handle: int) -> None: ...
    def is_foreground(self, handle: int) -> bool: ...
    def bring_launcher_to_foreground(self) -> None: ...


class CommandInputController(Protocol):
    def send_command(self, command: Command) -> None: ...


@dataclass(slots=True)
class TrackedApplication:
    app: ActiveApp
    process: ChildProcess
    window_handle: int | None


logger = logging.getLogger(__name__)
_WINDOW_DISCOVERY_TIMEOUT_SECONDS = 10.0


class ApplicationManager:
    def __init__(
        self,
        settings: Settings,
        *,
        executable_paths: Mapping[str, Path | None],
        process_launcher: Callable[[list[str]], ChildProcess] | None = None,
        windows: WindowController,
        input_controller: CommandInputController,
        adblock_dir: Path | None = None,
        profile_dir: Path | None = None,
    ) -> None:
        self._settings = settings
        self._executables = dict(executable_paths)
        self._launch_process = process_launcher or self._default_process_launcher
        self._windows = windows
        self._input = input_controller
        self._adblock_dir = adblock_dir or (project_root() / "vendor" / "adblock")
        self._profile_dir = profile_dir or (project_root() / "config" / "chrome-tv-profile")
        self._active_app = ActiveApp.LAUNCHER
        self._current: TrackedApplication | None = None
        self._children: list[TrackedApplication] = []

    @property
    def active_app(self) -> ActiveApp:
        return self._active_app

    def _chrome_kiosk_args(self, url: str) -> list[str]:
        chrome = self._executables.get("chrome")
        if chrome is None:
            raise CommandExecutionError(
                "chrome_not_found",
                "未安裝或尚未設定 Chrome。請安裝 Chrome，或在 applications.chrome_path 指定路徑。",
            )
        if not (self._adblock_dir / "manifest.json").is_file():
            raise CommandExecutionError(
                "adblock_not_installed",
                "尚未安裝 AdBlock。請重新執行 setup.ps1。",
            )
        extension_path = str(self._adblock_dir)
        return [
            chrome.as_posix(),
            f"--user-data-dir={self._profile_dir}",
            f"--disable-extensions-except={extension_path}",
            f"--load-extension={extension_path}",
            "--kiosk",
            "--no-first-run",
            "--no-default-browser-check",
            "--autoplay-policy=no-user-gesture-required",
            url,
        ]

    async def open(self, app: ActiveApp) -> None:
        if app not in {ActiveApp.YOUTUBE, ActiveApp.NETFLIX, ActiveApp.BROWSER}:
            raise CommandExecutionError(
                "unsupported_application", f"這個啟動器無法開啟 {app.value}。"
            )

        if app is ActiveApp.YOUTUBE:
            arguments = self._chrome_kiosk_args(self._settings.urls.youtube)
            await self._launch_and_track(app, arguments, "YouTube")
            return

        executable, url, app_name = self._launch_spec(app)
        if executable is None:
            raise CommandExecutionError(
                "application_not_found",
                f"未安裝或尚未設定{app_name}。請開啟設定進行設定。",
            )

        arguments = [executable.as_posix(), "--new-window", "--start-maximized", url]
        await self._launch_and_track(app, arguments, app_name)

    async def open_news(self, url: str) -> None:
        arguments = self._chrome_kiosk_args(url)
        await self._launch_and_track(ActiveApp.NEWS, arguments, "新聞")

    async def search_youtube(self, query: str) -> None:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        arguments = self._chrome_kiosk_args(url)
        await self._launch_and_track(ActiveApp.YOUTUBE, arguments, "YouTube")

    async def _launch_and_track(
        self, app: ActiveApp, arguments: list[str], app_name: str
    ) -> None:
        try:
            process = self._launch_process(arguments)
        except OSError as error:
            raise CommandExecutionError(
                "application_launch_failed", f"無法開啟{app_name}。"
            ) from error

        window_handle = await asyncio.to_thread(
            self._windows.find_window_for_pid,
            process.pid,
            _WINDOW_DISCOVERY_TIMEOUT_SECONDS,
        )
        tracked = TrackedApplication(app=app, process=process, window_handle=window_handle)
        if window_handle is None or not self._tracked_window_is_owned(tracked):
            if not await self._terminate_process(process):
                self._children.append(tracked)
            raise CommandExecutionError(
                "application_window_unavailable",
                (
                    f"無法取得控制器管理的{app_name}視窗。"
                    f"請先關閉現有的{app_name}視窗再試一次。"
                ),
            )
        self._windows.maximize(window_handle)
        if not self._tracked_window_is_owned(tracked):
            if not await self._terminate_process(process):
                self._children.append(tracked)
            raise CommandExecutionError(
                "application_window_unavailable",
                f"控制器管理的{app_name}視窗在就緒前已關閉。",
            )
        self._minimize_current_window()
        self._children.append(tracked)
        self._current = tracked
        self._active_app = app
        log_event(logger, "application_launched", app=app.value, process_id=process.pid)

    async def return_home(self) -> None:
        self._minimize_current_window()
        self._active_app = ActiveApp.LAUNCHER
        self._windows.bring_launcher_to_foreground()
        log_event(logger, "launcher_returned")

    async def forward_command(self, command: Command) -> None:
        self.require_input_target(self._active_app)
        self._input.send_command(command)

    def require_input_target(self, app: ActiveApp) -> None:
        if app not in {
            ActiveApp.YOUTUBE,
            ActiveApp.NETFLIX,
            ActiveApp.BROWSER,
            ActiveApp.NEWS,
        }:
            raise CommandExecutionError(
                "input_target_not_active",
                "請先開啟控制器管理的瀏覽器再使用遙控輸入。",
            )
        tracked = self._current
        if (
            self._active_app is not app
            or tracked is None
            or tracked.app is not app
            or not self._tracked_window_is_owned(tracked)
        ):
            raise CommandExecutionError(
                "input_target_unavailable",
                "控制器管理的應用程式視窗目前無法接受遙控輸入。",
            )
        assert tracked.window_handle is not None
        self._windows.activate(tracked.window_handle)
        if not self._tracked_window_is_owned(tracked):
            raise CommandExecutionError(
                "input_target_unavailable",
                "控制器管理的應用程式視窗目前無法接受遙控輸入。",
            )
        if not self._windows.is_foreground(tracked.window_handle):
            raise CommandExecutionError(
                "input_target_not_foreground",
                (
                    "請先把控制器開啟的應用程式切到前景，"
                    "再使用遙控輸入。"
                ),
            )

    async def shutdown(self) -> None:
        remaining: list[TrackedApplication] = []
        for tracked in self._children:
            if not await self._terminate_process(tracked.process):
                remaining.append(tracked)
        self._children = remaining
        self._current = None
        self._active_app = ActiveApp.LAUNCHER

    def _launch_spec(self, app: ActiveApp) -> tuple[Path | None, str, str]:
        if app is ActiveApp.YOUTUBE:
            return self._executables.get("brave"), self._settings.urls.youtube, "Brave 瀏覽器"
        if app is ActiveApp.NETFLIX:
            return self._executables.get("edge"), self._settings.urls.netflix, "Microsoft Edge"
        browser = self._executables.get("browser") or self._executables.get("edge")
        return browser, self._settings.urls.browser, "已設定的瀏覽器"

    def _minimize_current_window(self) -> None:
        if self._current is None or not self._tracked_window_is_owned(self._current):
            return
        assert self._current.window_handle is not None
        self._windows.minimize(self._current.window_handle)

    def _tracked_window_is_owned(self, tracked: TrackedApplication) -> bool:
        if tracked.window_handle is None:
            return False
        try:
            if tracked.process.poll() is not None:
                return False
        except OSError:
            return False
        return self._windows.window_belongs_to_process(tracked.window_handle, tracked.process.pid)

    @staticmethod
    async def _terminate_process(process: ChildProcess) -> bool:
        try:
            if process.poll() is not None:
                return True
            process.terminate()
            await asyncio.to_thread(process.wait, 2.0)
            return True
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                await asyncio.to_thread(process.wait, 2.0)
                return True
            except (OSError, subprocess.TimeoutExpired):
                return False
        except OSError:
            return False

    @staticmethod
    def _default_process_launcher(arguments: list[str]) -> ChildProcess:
        return subprocess.Popen(arguments)  # noqa: S603 - arguments are local typed settings only.
