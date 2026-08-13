from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Channel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    number: int = Field(ge=1, le=9999)
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def validate_stream_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https", "rtsp", "udp"}:
            raise ValueError("Channel URL must use http, https, rtsp, or udp.")
        if parsed.scheme in {"http", "https", "rtsp"} and not parsed.netloc:
            raise ValueError("Channel URL must include a host.")
        return value


class ChannelManager:
    def __init__(self, channels: list[Channel]) -> None:
        enabled = sorted((channel for channel in channels if channel.enabled), key=lambda channel: channel.number)
        if not enabled:
            raise ValueError("At least one enabled channel is required.")
        self._channels = enabled
        self._current_index = 0

    @property
    def current(self) -> Channel:
        return self._channels[self._current_index]

    @property
    def channels(self) -> tuple[Channel, ...]:
        return tuple(self._channels)

    def move(self, direction: int) -> Channel:
        if direction not in {-1, 1}:
            raise ValueError("Channel direction must be -1 or 1.")
        self._current_index = (self._current_index + direction) % len(self._channels)
        return self.current


def load_channels(path: Path) -> list[Channel]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"Channel configuration was not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError("Channel configuration is not valid JSON.") from error

    if not isinstance(raw, list):
        raise ValueError("Channel configuration must contain an array.")
    channels = [Channel.model_validate(item) for item in raw]
    ids = [channel.id for channel in channels]
    numbers = [channel.number for channel in channels]
    if len(ids) != len(set(ids)):
        raise ValueError("Channel IDs must be unique.")
    if len(numbers) != len(set(numbers)):
        raise ValueError("Channel numbers must be unique.")
    return channels
