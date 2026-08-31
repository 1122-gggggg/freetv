from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus

from app.applications.chrome_policy import TV_CHROME_NOTIFICATION_FLAGS
from app.applications.netflix_page import NetflixPageController
from app.applications.youtube_adfilter import YoutubeAdFilter, reserve_localhost_port
from app.applications.youtube_fullscreen import YoutubeFullscreenController, YoutubeQualityInfo
from app.commands.ports import CommandExecutionError
from app.config import Settings, project_root
from app.logging import log_event
from app.protocol import Command, NetflixContext
from app.state import ActiveApp

YOUTUBE_TV_USER_AGENT = (
    "Mozilla/5.0 (SMART-TV; Linux; Tizen 7.0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "SamsungBrowser/5.0 Chrome/120.0.6099.0 TV Safari/537.36"
)
CHROME_RESTORE_SUPPRESS_ARGS = (
    "--hide-crash-restore-bubble",
    "--disable-session-crashed-bubble",
    "--noerrdialogs",
)


def mark_chrome_profile_clean_exit(profile_dir: Path) -> None:
    prefs_path = profile_dir / "Default" / "Preferences"
    if not prefs_path.is_file():
        return
    try:
        data = json.loads(prefs_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    profile = data.get("profile")
    if not isinstance(profile, dict):
        profile = {}
        data["profile"] = profile
    profile["exit_type"] = "Normal"
    profile["exited_cleanly"] = True
    prefs_path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


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
    def close_launcher(self) -> None: ...
    def focus_window_with_title(self, title_fragment: str) -> int | None: ...
    def close_window(self, handle: int) -> None: ...


class CommandInputController(Protocol):
    def send_command(self, command: Command) -> None: ...
    def send_browser_back(self) -> None: ...


@dataclass(slots=True)
class TrackedApplication:
    app: ActiveApp
    process: ChildProcess
    window_handle: int | None


logger = logging.getLogger(__name__)
_WINDOW_DISCOVERY_TIMEOUT_SECONDS = 10.0
_NETFLIX_INITIALIZATION_ATTEMPTS = 20
_NETFLIX_INITIALIZATION_TIMEOUT_SECONDS = 20.0
_NETFLIX_INITIALIZATION_DELAY_SECONDS = 0.25
_APPLICATION_WATCH_INTERVAL_SECONDS = 0.25
_WINDOW_MISSING_GRACE_POLLS = 12
_NETFLIX_INITIALIZATION_RETRY_CODES = {
    "netflix_page_unavailable",
    "netflix_controller_unavailable",
    "netflix_focus_unavailable",
}


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
        adblock_youtube_dir: Path | None = None,
        profile_dir: Path | None = None,
        netflix_profile_dir: Path | None = None,
        adfilter: YoutubeAdFilter | None = None,
        youtube_fullscreen: YoutubeFullscreenController | None = None,
        netflix_page: NetflixPageController | None = None,
        debug_port: int | None = None,
        netflix_debug_port: int | None = None,
        on_application_exit: Callable[[ActiveApp], Awaitable[None]] | None = None,
        watch_interval_seconds: float = _APPLICATION_WATCH_INTERVAL_SECONDS,
    ) -> None:
        self._settings = settings
        self._executables = dict(executable_paths)
        self._launch_process = process_launcher or self._default_process_launcher
        self._windows = windows
        self._input = input_controller
        self._adblock_dir = adblock_dir or (project_root() / "vendor" / "adblock")
        self._adblock_youtube_dir = adblock_youtube_dir or (
            self._adblock_dir.parent / "adblock-youtube"
        )
        self._profile_dir = profile_dir or (project_root() / "config" / "chrome-tv-profile")
        self._netflix_profile_dir = netflix_profile_dir or (
            project_root() / "config" / "chrome-netflix-profile"
        )
        self._adfilter = adfilter or YoutubeAdFilter()
        self._youtube_fullscreen = youtube_fullscreen or YoutubeFullscreenController()
        self._debug_port = debug_port if debug_port is not None else reserve_localhost_port()
        self._netflix_debug_port = (
            netflix_debug_port if netflix_debug_port is not None else reserve_localhost_port()
        )
        self._netflix_page = netflix_page or NetflixPageController(self._netflix_debug_port)
        self._active_app = ActiveApp.LAUNCHER
        self._current: TrackedApplication | None = None
        self._children: list[TrackedApplication] = []
        self._on_application_exit = on_application_exit
        self._watch_interval_seconds = watch_interval_seconds
        self._watchers: dict[int, asyncio.Task[None]] = {}

    @property
    def active_app(self) -> ActiveApp:
        return self._active_app

    def set_application_exit_callback(
        self,
        callback: Callable[[ActiveApp], Awaitable[None]],
    ) -> None:
        self._on_application_exit = callback

    def _chrome_kiosk_args(self, url: str) -> list[str]:
        chrome = self._executables.get("chrome")
        if chrome is None:
            raise CommandExecutionError(
                "chrome_not_found",
                "未安裝或尚未設定 Chrome。請安裝 Chrome，或在 applications.chrome_path 指定路徑。",
            )
        mark_chrome_profile_clean_exit(self._profile_dir)
        return [
            chrome.as_posix(),
            f"--user-data-dir={self._profile_dir}",
            "--start-fullscreen",
            f"--user-agent={YOUTUBE_TV_USER_AGENT}",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self._debug_port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--autoplay-policy=no-user-gesture-required",
            *CHROME_RESTORE_SUPPRESS_ARGS,
            *TV_CHROME_NOTIFICATION_FLAGS,
            *ApplicationManager._posix_chrome_flags(),
            url,
        ]

    def _chrome_desktop_args(self, url: str, profile_dir: Path) -> list[str]:
        chrome = self._executables.get("chrome")
        if chrome is None:
            raise CommandExecutionError(
                "chrome_not_found",
                "未安裝或尚未設定 Chrome。請安裝 Chrome，或在 applications.chrome_path 指定路徑。",
            )
        mark_chrome_profile_clean_exit(profile_dir)
        return [
            chrome.as_posix(),
            f"--user-data-dir={profile_dir}",
            "--start-fullscreen",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self._netflix_debug_port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--autoplay-policy=no-user-gesture-required",
            *CHROME_RESTORE_SUPPRESS_ARGS,
            *TV_CHROME_NOTIFICATION_FLAGS,
            *ApplicationManager._posix_chrome_flags(),
            f"--app={url}",
        ]

    async def open(self, app: ActiveApp) -> NetflixContext | None:
        if app not in {ActiveApp.YOUTUBE, ActiveApp.NETFLIX, ActiveApp.BROWSER}:
            raise CommandExecutionError(
                "unsupported_application", f"這個啟動器無法開啟 {app.value}。"
            )

        if app is ActiveApp.YOUTUBE:
            await self._close_apps(ActiveApp.YOUTUBE, ActiveApp.NEWS)
            arguments = self._chrome_kiosk_args(self._settings.urls.youtube)
            await self._launch_and_track(app, arguments, "YouTube")
            return None
        if app is ActiveApp.NETFLIX:
            await self._close_apps(ActiveApp.YOUTUBE, ActiveApp.NEWS)
            if self._focus_existing(ActiveApp.NETFLIX):
                return await self._initialize_netflix(reused=True)
            arguments = self._chrome_desktop_args(
                self._settings.urls.netflix, self._netflix_profile_dir
            )
            await self._launch_and_track(app, arguments, "Netflix")
            return await self._initialize_netflix(reused=False)

        await self._close_apps(ActiveApp.YOUTUBE, ActiveApp.NEWS)
        executable, url, app_name = self._launch_spec(app)
        if executable is None:
            raise CommandExecutionError(
                "application_not_found",
                f"未安裝或尚未設定{app_name}。請開啟設定進行設定。",
            )

        arguments = [executable.as_posix(), "--new-window", "--start-maximized", url]
        await self._launch_and_track(app, arguments, app_name)
        return None

    async def open_news(self, url: str) -> None:
        await self._close_apps(ActiveApp.YOUTUBE, ActiveApp.NEWS)
        arguments = self._chrome_kiosk_args(url)
        await self._launch_and_track(ActiveApp.NEWS, arguments, "新聞")

    async def search_youtube(self, query: str) -> None:
        await self._close_apps(ActiveApp.YOUTUBE, ActiveApp.NEWS)
        url = f"https://www.youtube.com/tv#/search?q={quote_plus(query)}"
        arguments = self._chrome_kiosk_args(url)
        await self._launch_and_track(ActiveApp.YOUTUBE, arguments, "YouTube")

    async def _launch_and_track(self, app: ActiveApp, arguments: list[str], app_name: str) -> None:
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
                (f"無法取得控制器管理的{app_name}視窗。請先關閉現有的{app_name}視窗再試一次。"),
            )
        self._windows.maximize(window_handle)
        if not self._tracked_window_is_owned(tracked):
            if not await self._terminate_process(process):
                self._children.append(tracked)
            raise CommandExecutionError(
                "application_window_unavailable",
                f"控制器管理的{app_name}視窗在就緒前已關閉。",
            )
        if app in {ActiveApp.YOUTUBE, ActiveApp.NEWS}:
            try:
                await self._adfilter.attach(self._debug_port)
            except Exception:
                log_event(logger, "youtube_adfilter_failed", port=self._debug_port)
            try:
                await self._youtube_fullscreen.start(self._debug_port)
            except Exception:
                await self._youtube_fullscreen.stop()
                if not await self._stop_tracked(tracked):
                    self._children.append(tracked)
                raise
        self._minimize_current_window()
        self._children.append(tracked)
        self._current = tracked
        self._active_app = app
        log_event(logger, "application_launched", app=app.value, process_id=process.pid)
        self._start_watcher(tracked)

    async def return_home(self) -> None:
        await self._close_apps(ActiveApp.YOUTUBE, ActiveApp.NEWS)
        self._minimize_current_window()
        self._active_app = ActiveApp.LAUNCHER
        self._windows.bring_launcher_to_foreground()
        log_event(logger, "launcher_returned")

    async def leave_to_desktop(self) -> None:
        await self._close_apps(
            ActiveApp.YOUTUBE, ActiveApp.NEWS, ActiveApp.NETFLIX, ActiveApp.BROWSER
        )
        self._windows.close_launcher()
        self._active_app = ActiveApp.LAUNCHER
        log_event(logger, "returned_to_desktop")

    def _focus_existing(self, app: ActiveApp) -> bool:
        candidates = []
        if self._current is not None:
            candidates.append(self._current)
        candidates.extend(child for child in self._children if child is not self._current)
        for tracked in candidates:
            if tracked.app is not app or not self._tracked_window_is_owned(tracked):
                continue
            assert tracked.window_handle is not None
            self._windows.activate(tracked.window_handle)
            self._windows.maximize(tracked.window_handle)
            self._current = tracked
            self._active_app = app
            return True
        return False

    async def _close_apps(self, *apps: ActiveApp) -> None:
        current = self._current
        youtube_apps = (ActiveApp.YOUTUBE, ActiveApp.NEWS)
        closes_youtube = any(app in youtube_apps for app in apps)
        has_youtube = (current is not None and current.app in youtube_apps) or any(
            tracked.app in youtube_apps for tracked in self._children
        )
        if closes_youtube and has_youtube:
            await self._youtube_fullscreen.stop()
        kept: list[TrackedApplication] = []
        for tracked in self._children:
            if tracked.app in apps:
                await self._cancel_watcher(tracked)
                await self._stop_tracked(tracked)
            else:
                kept.append(tracked)
        if (
            current is not None
            and current.app in apps
            and all(tracked is not current for tracked in self._children)
        ):
            await self._cancel_watcher(current)
            await self._stop_tracked(current)
        self._children = kept
        if current is not None and current.app in apps:
            self._current = None

    async def type_text(self, text: str, submit: bool = False) -> NetflixContext | None:
        self.require_input_target(self._active_app)
        if self._active_app is ActiveApp.NETFLIX:
            return await self._netflix_page.type_text(text, submit=submit)
        raise CommandExecutionError(
            "input_target_not_active",
            "請先開啟 Netflix 再從遙控器輸入。",
        )

    async def _initialize_netflix(self, *, reused: bool) -> NetflixContext:
        try:
            async with asyncio.timeout(_NETFLIX_INITIALIZATION_TIMEOUT_SECONDS):
                for attempt in range(_NETFLIX_INITIALIZATION_ATTEMPTS):
                    try:
                        return await self._netflix_page.initialize()
                    except CommandExecutionError as error:
                        if (
                            error.code not in _NETFLIX_INITIALIZATION_RETRY_CODES
                            or attempt == _NETFLIX_INITIALIZATION_ATTEMPTS - 1
                        ):
                            raise
                        await asyncio.sleep(_NETFLIX_INITIALIZATION_DELAY_SECONDS)
                raise AssertionError("unreachable")
        except CommandExecutionError:
            await self._rollback_netflix_initialization(reused=reused)
            raise
        except TimeoutError:
            await self._rollback_netflix_initialization(reused=reused)
            raise CommandExecutionError(
                "netflix_controller_unavailable",
                "無法載入 Netflix 遙控控制，請稍後再試。",
            ) from None
        except Exception:
            await self._rollback_netflix_initialization(reused=reused)
            raise CommandExecutionError(
                "netflix_controller_unavailable",
                "無法載入 Netflix 遙控控制，請稍後再試。",
            ) from None

    async def _rollback_netflix_initialization(self, *, reused: bool) -> None:
        if reused:
            self._minimize_current_window()
        else:
            await self._close_apps(ActiveApp.NETFLIX)
        self._active_app = ActiveApp.LAUNCHER
        self._windows.bring_launcher_to_foreground()

    async def forward_command(self, command: Command) -> NetflixContext | None:
        self.require_input_target(self._active_app)
        if self._active_app is ActiveApp.NETFLIX:
            return await self._netflix_page.execute(command)
        if command is Command.FULLSCREEN and self._active_app in {
            ActiveApp.YOUTUBE,
            ActiveApp.NEWS,
        }:
            performed = False
            try:
                performed = await self._youtube_fullscreen.force_fullscreen(self._debug_port)
            except Exception:
                performed = False
            if not performed:
                self._input.send_command(command)
            return None
        if command is Command.BACK and self._active_app is ActiveApp.BROWSER:
            self._input.send_browser_back()
            return None
        self._input.send_command(command)
        return None

    async def adjust_playback_rate(self, direction: int) -> float:
        self.require_input_target(self._active_app)
        if self._active_app is ActiveApp.NETFLIX:
            command = Command.SPEED_UP if direction > 0 else Command.SPEED_DOWN
            await self._netflix_page.execute(command)
            return self._netflix_page.last_playback_rate
        if self._active_app in {ActiveApp.YOUTUBE, ActiveApp.NEWS}:
            return await self._youtube_fullscreen.adjust_playback_rate(
                self._debug_port,
                1 if direction > 0 else -1,
            )
        raise CommandExecutionError(
            "command_not_supported",
            "目前應用程式不支援這個操作。",
        )

    async def seek(self, direction: int) -> None:
        self.require_input_target(self._active_app)
        if self._active_app is ActiveApp.NETFLIX:
            command = Command.SEEK_FORWARD_5 if direction > 0 else Command.SEEK_BACKWARD_5
            await self._netflix_page.execute(command)
            return
        if self._active_app in {ActiveApp.YOUTUBE, ActiveApp.NEWS}:
            await self._youtube_fullscreen.seek(
                self._debug_port,
                1 if direction > 0 else -1,
            )
            return
        raise CommandExecutionError(
            "command_not_supported",
            "目前應用程式不支援這個操作。",
        )

    async def youtube_quality_info(self) -> YoutubeQualityInfo:
        if self._active_app is not ActiveApp.YOUTUBE:
            raise CommandExecutionError(
                "youtube_video_unavailable",
                "請先開啟 YouTube 影片再調整畫質。",
            )
        return await self._youtube_fullscreen.quality_info(self._debug_port)

    async def set_youtube_quality(self, quality: str) -> YoutubeQualityInfo:
        if self._active_app is not ActiveApp.YOUTUBE:
            raise CommandExecutionError(
                "youtube_video_unavailable",
                "請先開啟 YouTube 影片再調整畫質。",
            )
        return await self._youtube_fullscreen.set_quality(self._debug_port, quality)

    async def cycle_quality(self) -> str:
        self.require_input_target(self._active_app)
        if self._active_app in {ActiveApp.YOUTUBE, ActiveApp.NEWS}:
            return await self._youtube_fullscreen.cycle_quality(self._debug_port)
        if self._active_app is ActiveApp.NETFLIX:
            await self._netflix_page.execute(Command.QUALITY)
            return "最高畫質"
        raise CommandExecutionError(
            "command_not_supported",
            "目前應用程式不支援這個操作。",
        )

    async def toggle_subtitles(self) -> str:
        self.require_input_target(self._active_app)
        if self._active_app in {ActiveApp.YOUTUBE, ActiveApp.NEWS}:
            return await self._youtube_fullscreen.toggle_subtitles(self._debug_port)
        if self._active_app is ActiveApp.NETFLIX:
            await self._netflix_page.execute(Command.SUBTITLES)
            return "繁體中文"
        raise CommandExecutionError(
            "command_not_supported",
            "目前應用程式不支援這個操作。",
        )
    async def show_osd(self, text: str) -> None:
        if self._active_app in {ActiveApp.YOUTUBE, ActiveApp.NEWS}:
            show = getattr(self._youtube_fullscreen, "show_osd", None)
            if show is not None:
                try:
                    await show(self._debug_port, text)
                except Exception:
                    pass
        elif self._active_app is ActiveApp.NETFLIX:
            show = getattr(self._netflix_page, "show_osd", None)
            if show is not None:
                try:
                    await show(text)
                except Exception:
                    pass

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
        if app is ActiveApp.NETFLIX:
            return
        if not self._windows.is_foreground(tracked.window_handle):
            raise CommandExecutionError(
                "input_target_not_foreground",
                ("請先把控制器開啟的應用程式切到前景，再使用遙控輸入。"),
            )

    async def shutdown(self) -> None:
        await self._youtube_fullscreen.stop()
        await self._cancel_all_watchers()
        remaining: list[TrackedApplication] = []
        for tracked in self._children:
            if not await self._stop_tracked(tracked):
                remaining.append(tracked)
        self._children = remaining
        self._current = None
        self._active_app = ActiveApp.LAUNCHER

    def _launch_spec(self, app: ActiveApp) -> tuple[Path | None, str, str]:
        if app is ActiveApp.YOUTUBE:
            return self._executables.get("chrome"), self._settings.urls.youtube, "Google Chrome"
        if app is ActiveApp.NETFLIX:
            return self._executables.get("chrome"), self._settings.urls.netflix, "Google Chrome"
        browser = self._executables.get("browser") or self._executables.get("chrome")
        return browser, self._settings.urls.browser, "已設定的瀏覽器"

    def _minimize_current_window(self) -> None:
        if self._current is None or not self._tracked_window_is_owned(self._current):
            return
        assert self._current.window_handle is not None
        self._windows.minimize(self._current.window_handle)

    def _start_watcher(self, tracked: TrackedApplication) -> None:
        key = id(tracked)
        task = asyncio.create_task(self._watch_tracked(tracked))
        self._watchers[key] = task
        task.add_done_callback(
            lambda completed, watcher_key=key: self._discard_watcher(
                watcher_key,
                completed,
            )
        )

    def _discard_watcher(
        self,
        key: int,
        task: asyncio.Task[None],
    ) -> None:
        if self._watchers.get(key) is task:
            self._watchers.pop(key, None)

    async def _cancel_watcher(self, tracked: TrackedApplication) -> None:
        task = self._watchers.pop(id(tracked), None)
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _cancel_all_watchers(self) -> None:
        tasks = tuple(self._watchers.values())
        self._watchers.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _watch_tracked(self, tracked: TrackedApplication) -> None:
        timer = asyncio.Event()
        missing_window_polls = 0
        while True:
            try:
                await asyncio.wait_for(
                    timer.wait(),
                    timeout=self._watch_interval_seconds,
                )
            except TimeoutError:
                pass
            if not any(child is tracked for child in self._children):
                return
            try:
                process_exited = tracked.process.poll() is not None
            except OSError:
                process_exited = True
            if process_exited:
                await self._handle_unexpected_exit(tracked)
                return
            if self._tracked_window_is_owned(tracked):
                missing_window_polls = 0
                continue
            missing_window_polls += 1
            if missing_window_polls < _WINDOW_MISSING_GRACE_POLLS:
                continue
            await self._terminate_process(tracked.process)
            await self._handle_unexpected_exit(tracked)
            return

    async def _handle_unexpected_exit(self, tracked: TrackedApplication) -> None:
        if tracked.app in {ActiveApp.YOUTUBE, ActiveApp.NEWS}:
            await self._youtube_fullscreen.stop()
        self._children = [child for child in self._children if child is not tracked]
        if self._current is tracked:
            self._current = None
            self._active_app = ActiveApp.LAUNCHER
        log_event(
            logger,
            "application_exited",
            app=tracked.app.value,
            process_id=tracked.process.pid,
        )
        if self._on_application_exit is not None:
            try:
                await self._on_application_exit(tracked.app)
            except Exception:
                log_event(
                    logger,
                    "application_exit_callback_failed",
                    app=tracked.app.value,
                )

    def _tracked_window_is_owned(self, tracked: TrackedApplication) -> bool:
        try:
            if tracked.process.poll() is not None:
                return False
        except OSError:
            return False
        if tracked.window_handle is not None and self._windows.window_belongs_to_process(
            tracked.window_handle,
            tracked.process.pid,
        ):
            return True
        replacement = self._windows.find_window_for_pid(tracked.process.pid, 0.0)
        if replacement is None or replacement == tracked.window_handle:
            return False
        if not self._windows.window_belongs_to_process(replacement, tracked.process.pid):
            return False
        tracked.window_handle = replacement
        return True

    async def _stop_tracked(self, tracked: TrackedApplication) -> bool:
        if tracked.window_handle is not None:
            try:
                self._windows.close_window(tracked.window_handle)
                await asyncio.to_thread(tracked.process.wait, 2.0)
                return True
            except (OSError, subprocess.TimeoutExpired):
                pass
        return await self._terminate_process(tracked.process)

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
    def _posix_chrome_flags() -> list[str]:
        if os.name == "nt":
            return []
        return ["--password-store=basic", "--ozone-platform-hint=auto"]

    @staticmethod
    def _default_process_launcher(arguments: list[str]) -> ChildProcess:
        kwargs: dict[str, object] = {}
        if os.name != "nt":
            kwargs["start_new_session"] = True
        return subprocess.Popen(arguments, **kwargs)  # noqa: S603 - arguments are local typed settings only.
