from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from app.applications.manager import ApplicationManager
from app.commands.bus import CommandBus
from app.commands.ports import CommandExecutionError
from app.config import Settings, project_root, resolve_application_paths
from app.discovery.advertiser import ServiceAdvertiser
from app.player.channels import ChannelManager, load_channels
from app.player.mpv import MpvController
from app.security.pairing import PairingService
from app.security.tokens import TokenStore
from app.state import StateStore
from app.system.input import WindowsInputController
from app.system.power import WindowsPowerController
from app.system.volume import WindowsVolumeController
from app.system.windows import WindowsWindowController


class UnavailablePlayer:
    def __init__(self, message: str) -> None:
        self._message = message

    async def open(self) -> tuple[int, str]:
        raise CommandExecutionError("live_tv_unavailable", self._message)

    async def close(self) -> None:
        return None

    async def toggle_pause(self) -> None:
        raise CommandExecutionError("live_tv_unavailable", self._message)

    async def next(self) -> None:
        raise CommandExecutionError("live_tv_unavailable", self._message)

    async def previous(self) -> None:
        raise CommandExecutionError("live_tv_unavailable", self._message)

    async def change_channel(self, direction: int) -> tuple[int, str]:
        raise CommandExecutionError("live_tv_unavailable", self._message)


@dataclass(slots=True)
class ControllerRuntime:
    bus: CommandBus
    pairing: PairingService
    applications: object
    player: object
    advertiser: ServiceAdvertiser | None = None

    async def startup(self) -> None:
        if self.advertiser is not None:
            await self.advertiser.start()

    async def shutdown(self) -> None:
        if self.advertiser is not None:
            await self.advertiser.stop()
        close_player = getattr(self.player, "close", None)
        if close_player is not None:
            await close_player()
        shutdown_applications = getattr(self.applications, "shutdown", None)
        if shutdown_applications is not None:
            await shutdown_applications()

def build_runtime(settings: Settings) -> ControllerRuntime:
    executable_paths = resolve_application_paths(settings)
    input_controller = WindowsInputController()
    applications = ApplicationManager(
        settings,
        executable_paths=executable_paths,
        windows=WindowsWindowController(),
        input_controller=input_controller,
    )
    player = _build_player(settings, executable_paths["mpv"])
    tokens = TokenStore(
        project_root() / "config" / "remotes.json",
        token_bytes=settings.security.remote_token_bytes,
        token_ttl=timedelta(days=settings.security.remote_token_ttl_days),
    )
    pairing = PairingService(
        tokens,
        ttl=timedelta(seconds=settings.security.pairing_code_ttl_seconds),
    )
    bus = CommandBus(
        StateStore(),
        applications=applications,
        player=player,
        volume=WindowsVolumeController(),
        input_controller=input_controller,
        power=WindowsPowerController(),
    )
    advertiser = (
        ServiceAdvertiser(port=settings.server.port)
        if settings.server.transport == "https"
        else None
    )
    return ControllerRuntime(
        bus=bus,
        pairing=pairing,
        applications=applications,
        player=player,
        advertiser=advertiser,
    )


def _build_player(settings: Settings, mpv_path: Path | None) -> MpvController | UnavailablePlayer:
    channels_path = project_root() / "config" / "channels.json"
    if not channels_path.exists():
        channels_path = project_root() / "config" / "channels.example.json"
    try:
        channels = ChannelManager(load_channels(channels_path))
    except ValueError:
        return UnavailablePlayer(
            "No enabled Live TV channels are configured. Update config/channels.json."
        )
    return MpvController(channels, mpv_path=mpv_path)
