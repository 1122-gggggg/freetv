from __future__ import annotations

import asyncio
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.protocol import NetflixContext, StateMessage


class ActiveApp(StrEnum):
    LAUNCHER = "launcher"
    YOUTUBE = "youtube"
    NETFLIX = "netflix"
    LIVE_TV = "live_tv"
    BROWSER = "browser"
    NEWS = "news"


class LauncherTile(StrEnum):
    YOUTUBE = "youtube"
    NETFLIX = "netflix"
    NEWS = "news"


class ControllerState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    active_app: ActiveApp = ActiveApp.LAUNCHER
    focused_tile: LauncherTile = LauncherTile.YOUTUBE
    volume: int = Field(default=50, ge=0, le=100)
    muted: bool = False
    brightness: int = Field(default=100, ge=10, le=100)
    channel_number: int | None = Field(default=None, ge=1)
    channel_name: str | None = Field(default=None, max_length=120)
    status_message: str | None = Field(default=None, max_length=256)
    error_message: str | None = Field(default=None, max_length=256)
    netflix_context: NetflixContext | None = None
    update_available: str | None = None

    def to_wire(self) -> StateMessage:
        return StateMessage(
            active_app=self.active_app.value,
            focused_tile=self.focused_tile.value,
            volume=self.volume,
            muted=self.muted,
            brightness=self.brightness,
            channel_number=self.channel_number,
            channel_name=self.channel_name,
            status_message=self.status_message,
            error_message=self.error_message,
            netflix_context=self.netflix_context,
            update_available=self.update_available,
        )


class StateStore:
    def __init__(self, initial: ControllerState | None = None) -> None:
        self._state = initial or ControllerState()
        self._lock = asyncio.Lock()

    async def snapshot(self) -> ControllerState:
        async with self._lock:
            return self._state.model_copy(deep=True)

    async def update(self, **changes: object) -> ControllerState:
        async with self._lock:
            state_data = self._state.model_dump()
            state_data.update(changes)
            self._state = ControllerState.model_validate(state_data)
            return self._state.model_copy(deep=True)
