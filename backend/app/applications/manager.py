from __future__ import annotations

import asyncio
import logging
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.commands.ports import CommandExecutionError
from app.config import Settings
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
    ) -> None:
        self._settings = settings
        self._executables = dict(executable_paths)
        self._launch_process = process_launcher or self._default_process_launcher
        self._windows = windows
        self._input = input_controller
        self._active_app = ActiveApp.LAUNCHER
        self._current: TrackedApplication | None = None
        self._children: list[TrackedApplication] = []

    @property
    def active_app(self) -> ActiveApp:
        return self._active_app

    async def open(self, app: ActiveApp) -> None:
        if app not in {ActiveApp.YOUTUBE, ActiveApp.NETFLIX, ActiveApp.BROWSER}:
            raise CommandExecutionError(
                "unsupported_application", f"{app.value} is not opened by this launcher."
            )

        executable, url, app_name = self._launch_spec(app)
        if executable is None:
            raise CommandExecutionError(
                "application_not_found",
                f"{app_name} is not installed or configured. Open Settings to configure it.",
            )

        arguments = [executable.as_posix(), "--new-window", "--start-maximized", url]
        try:
            process = self._launch_process(arguments)
        except OSError as error:
            raise CommandExecutionError(
                "application_launch_failed", f"Could not open {app_name}."
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
                    f"Could not secure a controller-managed {app_name} window. "
                    f"Close existing {app_name} windows and try again."
                ),
            )
        self._windows.maximize(window_handle)
        if not self._tracked_window_is_owned(tracked):
            if not await self._terminate_process(process):
                self._children.append(tracked)
            raise CommandExecutionError(
                "application_window_unavailable",
                f"The controller-managed {app_name} window closed before it was ready.",
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
        if app not in {ActiveApp.YOUTUBE, ActiveApp.NETFLIX, ActiveApp.BROWSER}:
            raise CommandExecutionError(
                "input_target_not_active",
                "Open a controller-managed browser before using remote input.",
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
                "The controller-managed application window is not available for remote input.",
            )
        assert tracked.window_handle is not None
        self._windows.activate(tracked.window_handle)
        if not self._tracked_window_is_owned(tracked):
            raise CommandExecutionError(
                "input_target_unavailable",
                "The controller-managed application window is not available for remote input.",
            )
        if not self._windows.is_foreground(tracked.window_handle):
            raise CommandExecutionError(
                "input_target_not_foreground",
                (
                    "Bring the controller-opened application to the foreground "
                    "before using remote input."
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
            return self._executables.get("brave"), self._settings.urls.youtube, "Brave browser"
        if app is ActiveApp.NETFLIX:
            return self._executables.get("edge"), self._settings.urls.netflix, "Microsoft Edge"
        browser = self._executables.get("browser") or self._executables.get("edge")
        return browser, self._settings.urls.browser, "Configured browser"

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
