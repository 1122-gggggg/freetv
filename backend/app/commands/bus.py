from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.commands.ports import (
    ApplicationPort,
    CommandExecutionError,
    InputPort,
    NewsPort,
    PlayerPort,
    PowerPort,
    VolumePort,
)
from app.protocol import Command, PointerActionMessage, SearchVideoMessage, TextInputMessage
from app.state import ActiveApp, ControllerState, LauncherTile, StateStore


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    success: bool
    state: ControllerState
    error_code: str | None = None
    message: str | None = None
    state_changed: bool = True


_TILE_COMMANDS: dict[LauncherTile, Command] = {
    LauncherTile.YOUTUBE: Command.OPEN_YOUTUBE,
    LauncherTile.NETFLIX: Command.OPEN_NETFLIX,
    LauncherTile.LIVE_TV: Command.OPEN_LIVE_TV,
    LauncherTile.BROWSER: Command.OPEN_BROWSER,
    LauncherTile.NEWS: Command.OPEN_NEWS,
}

_LAUNCH_TARGETS: dict[Command, ActiveApp] = {
    Command.OPEN_YOUTUBE: ActiveApp.YOUTUBE,
    Command.OPEN_NETFLIX: ActiveApp.NETFLIX,
    Command.OPEN_BROWSER: ActiveApp.BROWSER,
}

_FOCUS_TRANSITIONS: dict[tuple[LauncherTile, Command], LauncherTile] = {
    (LauncherTile.YOUTUBE, Command.NAV_RIGHT): LauncherTile.NETFLIX,
    (LauncherTile.NETFLIX, Command.NAV_LEFT): LauncherTile.YOUTUBE,
    (LauncherTile.LIVE_TV, Command.NAV_RIGHT): LauncherTile.BROWSER,
    (LauncherTile.BROWSER, Command.NAV_LEFT): LauncherTile.LIVE_TV,
    (LauncherTile.YOUTUBE, Command.NAV_DOWN): LauncherTile.LIVE_TV,
    (LauncherTile.NETFLIX, Command.NAV_DOWN): LauncherTile.BROWSER,
    (LauncherTile.LIVE_TV, Command.NAV_UP): LauncherTile.YOUTUBE,
    (LauncherTile.BROWSER, Command.NAV_UP): LauncherTile.NETFLIX,
    (LauncherTile.LIVE_TV, Command.NAV_DOWN): LauncherTile.SETTINGS,
    (LauncherTile.BROWSER, Command.NAV_DOWN): LauncherTile.SETTINGS,
    (LauncherTile.SETTINGS, Command.NAV_UP): LauncherTile.LIVE_TV,
}


class CommandBus:
    def __init__(
        self,
        state: StateStore,
        *,
        applications: ApplicationPort,
        player: PlayerPort,
        volume: VolumePort,
        input_controller: InputPort,
        power: PowerPort,
        news: NewsPort,
    ) -> None:
        self._state = state
        self._applications = applications
        self._player = player
        self._volume = volume
        self._input = input_controller
        self._power = power
        self._news = news
        self._command_lock = asyncio.Lock()
    async def dispatch_command(self, command: Command) -> CommandOutcome:
        async with self._command_lock:
            try:
                return await self._dispatch_command(command)
            except CommandExecutionError as error:
                state = await self._state.update(error_message=error.message, status_message=None)
                return CommandOutcome(False, state, error.code, error.message)
            except Exception:
                state = await self._state.update(
                    error_message="The controller could not complete that action.",
                    status_message=None,
                )
                return CommandOutcome(
                    False,
                    state,
                    "controller_error",
                    "The controller could not complete that action.",
                )

    async def dispatch_pointer(self, message: PointerActionMessage) -> CommandOutcome:
        async with self._command_lock:
            try:
                self._require_external_input_target(await self._state.snapshot())
                await self._input.pointer(message)
                return await self._passive_success()
            except CommandExecutionError as error:
                return await self._failure(error)
            except Exception:
                return await self._unknown_failure()

    async def dispatch_text(self, message: TextInputMessage) -> CommandOutcome:
        async with self._command_lock:
            try:
                self._require_external_input_target(await self._state.snapshot())
                await self._input.text(message.text)
                return await self._passive_success()
            except CommandExecutionError as error:
                return await self._failure(error)
            except Exception:
                return await self._unknown_failure()

    async def dispatch_search(self, message: SearchVideoMessage) -> CommandOutcome:
        async with self._command_lock:
            try:
                current = await self._state.snapshot()
                if current.active_app is ActiveApp.LIVE_TV:
                    await self._player.close()
                    try:
                        await self._applications.search_youtube(message.query)
                    except Exception:
                        await self._applications.return_home()
                        await self._state.update(
                            active_app=ActiveApp.LAUNCHER,
                            channel_number=None,
                            channel_name=None,
                            status_message=None,
                        )
                        raise
                else:
                    await self._applications.search_youtube(message.query)
                state = await self._state.update(
                    active_app=ActiveApp.YOUTUBE,
                    channel_number=None,
                    channel_name=None,
                    error_message=None,
                    status_message=None,
                )
                return CommandOutcome(True, state)
            except CommandExecutionError as error:
                return await self._failure(error)
            except Exception:
                return await self._unknown_failure()

    async def state_snapshot(self) -> ControllerState:
        return await self._state.snapshot()

    async def _dispatch_command(self, command: Command) -> CommandOutcome:
        current = await self._state.snapshot()
        if command is Command.HOME:
            if current.active_app is ActiveApp.LIVE_TV:
                await self._player.close()
            await self._applications.return_home()
            state = await self._state.update(
                active_app=ActiveApp.LAUNCHER,
                channel_number=None,
                channel_name=None,
                error_message=None,
                status_message=None,
            )
            return CommandOutcome(True, state)

        if command is Command.POWER_SLEEP:
            await self._power.sleep()
            state = await self._success_state(status_message="PC is going to sleep.")
            return CommandOutcome(True, state)

        if command in _LAUNCH_TARGETS:
            target = _LAUNCH_TARGETS[command]
            if current.active_app is ActiveApp.LIVE_TV:
                await self._player.close()
                try:
                    await self._applications.open(target)
                except Exception:
                    await self._applications.return_home()
                    await self._state.update(
                        active_app=ActiveApp.LAUNCHER,
                        channel_number=None,
                        channel_name=None,
                        status_message=None,
                    )
                    raise
            else:
                await self._applications.open(target)
            state = await self._state.update(
                active_app=_LAUNCH_TARGETS[command],
                channel_number=None,
                channel_name=None,
                error_message=None,
                status_message=None,
            )
            return CommandOutcome(True, state)

        if command is Command.OPEN_LIVE_TV:
            channel_number, channel_name = await self._player.open()
            state = await self._state.update(
                active_app=ActiveApp.LIVE_TV,
                channel_number=channel_number,
                channel_name=channel_name,
                error_message=None,
                status_message=None,
            )
            return CommandOutcome(True, state)
        if command is Command.OPEN_NEWS:
            channel = self._news.current
            if current.active_app is ActiveApp.LIVE_TV:
                await self._player.close()
                try:
                    await self._applications.open_news(channel.url)
                except Exception:
                    await self._applications.return_home()
                    await self._state.update(
                        active_app=ActiveApp.LAUNCHER,
                        channel_number=None,
                        channel_name=None,
                        status_message=None,
                    )
                    raise
            else:
                await self._applications.open_news(channel.url)
            state = await self._state.update(
                active_app=ActiveApp.NEWS,
                channel_number=channel.number,
                channel_name=channel.name,
                error_message=None,
                status_message=None,
            )
            return CommandOutcome(True, state)


        if command in {Command.NAV_UP, Command.NAV_DOWN, Command.NAV_LEFT, Command.NAV_RIGHT}:
            return await self._navigate(current, command)

        if command is Command.OK and current.active_app is ActiveApp.LAUNCHER:
            target = _TILE_COMMANDS.get(current.focused_tile)
            if target is None:
                state = await self._success_state(
                    status_message="Settings are configured in config/settings.json."
                )
                return CommandOutcome(True, state)
            return await self._dispatch_command(target)

        if command is Command.BACK and current.active_app is ActiveApp.LAUNCHER:
            return await self._passive_success()

        if command is Command.PLAY_PAUSE and current.active_app is ActiveApp.LIVE_TV:
            await self._player.toggle_pause()
            return await self._passive_success()

        if command is Command.NEXT and current.active_app is ActiveApp.LIVE_TV:
            await self._player.next()
            return await self._passive_success()

        if command is Command.PREVIOUS and current.active_app is ActiveApp.LIVE_TV:
            await self._player.previous()
            return await self._passive_success()

        if command in {Command.CHANNEL_UP, Command.CHANNEL_DOWN}:
            direction = 1 if command is Command.CHANNEL_UP else -1
            if current.active_app is ActiveApp.NEWS:
                channel = self._news.move(direction)
                await self._applications.open_news(channel.url)
                state = await self._state.update(
                    channel_number=channel.number,
                    channel_name=channel.name,
                    error_message=None,
                    status_message=None,
                )
                return CommandOutcome(True, state)
            if current.active_app is ActiveApp.LIVE_TV:
                channel_number, channel_name = await self._player.change_channel(direction)
                state = await self._state.update(
                    channel_number=channel_number,
                    channel_name=channel_name,
                    error_message=None,
                    status_message=None,
                )
                return CommandOutcome(True, state)
            raise CommandExecutionError(
                "channel_source_not_active", "Open News or Live TV before changing channels."
            )
        if command is Command.VOLUME_UP:
            level, muted = await self._volume.increase()
            return CommandOutcome(True, await self._success_state(volume=level, muted=muted))

        if command is Command.VOLUME_DOWN:
            level, muted = await self._volume.decrease()
            return CommandOutcome(True, await self._success_state(volume=level, muted=muted))

        if command is Command.MUTE:
            level, muted = await self._volume.toggle_mute()
            return CommandOutcome(True, await self._success_state(volume=level, muted=muted))

        if current.active_app in {
            ActiveApp.YOUTUBE,
            ActiveApp.NETFLIX,
            ActiveApp.BROWSER,
            ActiveApp.NEWS,
        }:
            await self._applications.forward_command(command)
            return await self._passive_success()
        raise CommandExecutionError(
            "command_not_supported", "That control is not available for the active application."
        )

    async def _navigate(self, current: ControllerState, command: Command) -> CommandOutcome:
        if current.active_app is not ActiveApp.LAUNCHER:
            if current.active_app in {
                ActiveApp.YOUTUBE,
                ActiveApp.NETFLIX,
                ActiveApp.BROWSER,
                ActiveApp.NEWS,
            }:
                await self._applications.forward_command(command)
                return await self._passive_success()
            raise CommandExecutionError(
                "command_not_supported", "That control is not available for the active application."
            )

        focused_tile = _FOCUS_TRANSITIONS.get((current.focused_tile, command), current.focused_tile)
        state = await self._success_state(focused_tile=focused_tile)
        return CommandOutcome(True, state)

    def _require_external_input_target(self, current: ControllerState) -> None:
        if current.active_app not in {
            ActiveApp.YOUTUBE,
            ActiveApp.NETFLIX,
            ActiveApp.BROWSER,
            ActiveApp.NEWS,
        }:
            raise CommandExecutionError(
                "input_target_not_active",
                "Open a controller-managed browser before using remote input.",
            )
        self._applications.require_input_target(current.active_app)

    async def _success_state(self, **changes: object) -> ControllerState:
        return await self._state.update(error_message=None, **changes)

    async def _passive_success(self) -> CommandOutcome:
        state = await self._state.snapshot()
        if state.error_message is not None:
            return CommandOutcome(True, await self._success_state())
        return CommandOutcome(True, state, state_changed=False)

    async def _failure(self, error: CommandExecutionError) -> CommandOutcome:
        state = await self._state.update(error_message=error.message, status_message=None)
        return CommandOutcome(False, state, error.code, error.message)

    async def _unknown_failure(self) -> CommandOutcome:
        message = "The controller could not complete that action."
        state = await self._state.update(error_message=message, status_message=None)
        return CommandOutcome(False, state, "controller_error", message)
