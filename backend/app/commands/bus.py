from __future__ import annotations

from dataclasses import dataclass

from app.commands.ports import (
    ApplicationPort,
    CommandExecutionError,
    InputPort,
    PlayerPort,
    PowerPort,
    VolumePort,
)
from app.protocol import Command, PointerActionMessage, TextInputMessage
from app.state import ActiveApp, ControllerState, LauncherTile, StateStore


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    success: bool
    state: ControllerState
    error_code: str | None = None
    message: str | None = None


_TILE_COMMANDS: dict[LauncherTile, Command] = {
    LauncherTile.YOUTUBE: Command.OPEN_YOUTUBE,
    LauncherTile.NETFLIX: Command.OPEN_NETFLIX,
    LauncherTile.LIVE_TV: Command.OPEN_LIVE_TV,
    LauncherTile.BROWSER: Command.OPEN_BROWSER,
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
    ) -> None:
        self._state = state
        self._applications = applications
        self._player = player
        self._volume = volume
        self._input = input_controller
        self._power = power

    async def dispatch_command(self, command: Command) -> CommandOutcome:
        try:
            return await self._dispatch_command(command)
        except CommandExecutionError as error:
            state = await self._state.update(error_message=error.message, status_message=None)
            return CommandOutcome(False, state, error.code, error.message)
        except Exception:
            state = await self._state.update(
                error_message="The controller could not complete that action.", status_message=None
            )
            return CommandOutcome(False, state, "controller_error", "The controller could not complete that action.")

    async def dispatch_pointer(self, message: PointerActionMessage) -> CommandOutcome:
        try:
            await self._input.pointer(message)
            state = await self._success_state()
            return CommandOutcome(True, state)
        except CommandExecutionError as error:
            return await self._failure(error)
        except Exception:
            return await self._unknown_failure()

    async def dispatch_text(self, message: TextInputMessage) -> CommandOutcome:
        try:
            await self._input.text(message.text)
            state = await self._success_state()
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
            await self._applications.open(_LAUNCH_TARGETS[command])
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
            return CommandOutcome(True, await self._success_state())

        if command is Command.PLAY_PAUSE and current.active_app is ActiveApp.LIVE_TV:
            await self._player.toggle_pause()
            return CommandOutcome(True, await self._success_state())

        if command is Command.NEXT and current.active_app is ActiveApp.LIVE_TV:
            await self._player.next()
            return CommandOutcome(True, await self._success_state())

        if command is Command.PREVIOUS and current.active_app is ActiveApp.LIVE_TV:
            await self._player.previous()
            return CommandOutcome(True, await self._success_state())

        if command in {Command.CHANNEL_UP, Command.CHANNEL_DOWN}:
            if current.active_app is not ActiveApp.LIVE_TV:
                raise CommandExecutionError("live_tv_not_active", "Open Live TV before changing channels.")
            direction = 1 if command is Command.CHANNEL_UP else -1
            channel_number, channel_name = await self._player.change_channel(direction)
            state = await self._state.update(
                channel_number=channel_number,
                channel_name=channel_name,
                error_message=None,
                status_message=None,
            )
            return CommandOutcome(True, state)

        if command is Command.VOLUME_UP:
            level, muted = await self._volume.increase()
            return CommandOutcome(True, await self._success_state(volume=level, muted=muted))

        if command is Command.VOLUME_DOWN:
            level, muted = await self._volume.decrease()
            return CommandOutcome(True, await self._success_state(volume=level, muted=muted))

        if command is Command.MUTE:
            level, muted = await self._volume.toggle_mute()
            return CommandOutcome(True, await self._success_state(volume=level, muted=muted))

        await self._applications.forward_command(command)
        return CommandOutcome(True, await self._success_state())

    async def _navigate(self, current: ControllerState, command: Command) -> CommandOutcome:
        if current.active_app is not ActiveApp.LAUNCHER:
            await self._applications.forward_command(command)
            return CommandOutcome(True, await self._success_state())

        focused_tile = _FOCUS_TRANSITIONS.get((current.focused_tile, command), current.focused_tile)
        state = await self._success_state(focused_tile=focused_tile)
        return CommandOutcome(True, state)

    async def _success_state(self, **changes: object) -> ControllerState:
        return await self._state.update(error_message=None, **changes)

    async def _failure(self, error: CommandExecutionError) -> CommandOutcome:
        state = await self._state.update(error_message=error.message, status_message=None)
        return CommandOutcome(False, state, error.code, error.message)

    async def _unknown_failure(self) -> CommandOutcome:
        message = "The controller could not complete that action."
        state = await self._state.update(error_message=message, status_message=None)
        return CommandOutcome(False, state, "controller_error", message)
