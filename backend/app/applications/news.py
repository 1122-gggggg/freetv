from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from pydantic import field_validator

from app.player.channels import Channel, ChannelManager

YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com"})


class NewsChannel(Channel):
    @field_validator("url")
    @classmethod
    def validate_youtube_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https":
            raise ValueError("News channel URL must use https.")
        hostname = (parsed.hostname or "").lower()
        if hostname not in YOUTUBE_HOSTS:
            raise ValueError("News channel URL must be on youtube.com or www.youtube.com.")
        return value


class NewsChannelManager(ChannelManager):
    pass


def load_news_channels(path: Path) -> list[Channel]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"News channel configuration was not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError("News channel configuration is not valid JSON.") from error

    if not isinstance(raw, list):
        raise ValueError("News channel configuration must contain an array.")
    channels = [NewsChannel.model_validate(item) for item in raw]
    ids = [channel.id for channel in channels]
    numbers = [channel.number for channel in channels]
    if len(ids) != len(set(ids)):
        raise ValueError("News channel IDs must be unique.")
    if len(numbers) != len(set(numbers)):
        raise ValueError("News channel numbers must be unique.")
    return channels
