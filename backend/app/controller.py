from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from app.applications.manager import ApplicationManager
from app.applications.news import NewsChannelManager, load_news_channels
from app.commands.bus import CommandBus
from app.commands.ports import CommandExecutionError
from app.config import Settings, project_root, resolve_application_paths
from app.discovery.advertiser import ServiceAdvertiser
from app.player.channels import Channel, ChannelManager, load_channels
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


class UnavailableNews:
    def __init__(self, message: str) -> None:
        self._message = message

    @property
    def current(self) -> Channel:
        raise CommandExecutionError("news_not_configured", self._message)

    def move(self, direction: int) -> Channel:
        raise CommandExecutionError("news_not_configured", self._message)


@dataclass(slots=True)
class ControllerRuntime:
    bus: CommandBus
    pairing: PairingService
    applications: object
    player: object
    news: object = None
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
    news = _build_news(settings)
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
        news=news,
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
        news=news,
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
            "尚未設定可用的電視頻道。請更新 config/channels.json。"
        )
    return MpvController(channels, mpv_path=mpv_path)


def _build_news(settings: Settings) -> NewsChannelManager | UnavailableNews:
    news_path = project_root() / "config" / "news.json"
    if not news_path.exists():
        news_path = project_root() / "config" / "news.example.json"
    try:
        channels = load_news_channels(news_path)
        return NewsChannelManager(channels)
    except (ValueError, FileNotFoundError):
        return UnavailableNews(
            "尚未設定可用的新聞頻道。請更新 config/news.json。"
        )
