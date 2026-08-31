from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

PROTOCOL_VERSION = 1
REQUEST_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$"


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Command(StrEnum):
    NAV_UP = "NAV_UP"
    NAV_DOWN = "NAV_DOWN"
    NAV_LEFT = "NAV_LEFT"
    NAV_RIGHT = "NAV_RIGHT"
    OK = "OK"
    BACK = "BACK"
    TAB = "TAB"
    HOME = "HOME"
    PLAY_PAUSE = "PLAY_PAUSE"
    FULLSCREEN = "FULLSCREEN"
    SPEED_UP = "SPEED_UP"
    SPEED_DOWN = "SPEED_DOWN"
    SEEK_FORWARD_5 = "SEEK_FORWARD_5"
    SEEK_BACKWARD_5 = "SEEK_BACKWARD_5"
    NEXT = "NEXT"
    PREVIOUS = "PREVIOUS"
    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"
    MUTE = "MUTE"
    BRIGHTNESS_UP = "BRIGHTNESS_UP"
    BRIGHTNESS_DOWN = "BRIGHTNESS_DOWN"
    CHANNEL_UP = "CHANNEL_UP"
    CHANNEL_DOWN = "CHANNEL_DOWN"
    OPEN_YOUTUBE = "OPEN_YOUTUBE"
    OPEN_NETFLIX = "OPEN_NETFLIX"
    OPEN_LIVE_TV = "OPEN_LIVE_TV"
    OPEN_BROWSER = "OPEN_BROWSER"
    OPEN_NEWS = "OPEN_NEWS"
    POWER_SLEEP = "POWER_SLEEP"
    QUALITY = "QUALITY"
    SUBTITLES = "SUBTITLES"
class NetflixStage(StrEnum):
    LOGIN = "login"
    VERIFICATION = "verification"
    BROWSE = "browse"
    DETAILS = "details"
    WATCH = "watch"
    UNKNOWN = "unknown"


class NetflixInputKind(StrEnum):
    EMAIL = "email"
    PASSWORD = "password"
    CODE = "code"
    SEARCH = "search"
    NONE = "none"


class NetflixContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: NetflixStage
    input_kind: NetflixInputKind
    has_error: bool = Field(default=False, strict=True)
    can_submit: bool = Field(default=False, strict=True)
    focused_title: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def title_is_browse_only(self) -> NetflixContext:
        if self.stage is not NetflixStage.BROWSE and self.focused_title is not None:
            raise ValueError("focused_title is only valid during browse")
        return self


class PointerAction(StrEnum):
    MOVE = "move"
    TAP = "tap"
    DOUBLE_TAP = "double_tap"
    SCROLL = "scroll"


class AuthenticationMessage(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["authenticate"]
    request_id: str = Field(min_length=1, max_length=64, pattern=REQUEST_ID_PATTERN)
    token: str = Field(min_length=32, max_length=512)


class CommandMessage(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["command"]
    request_id: str = Field(min_length=1, max_length=64, pattern=REQUEST_ID_PATTERN)
    command: Command


class PointerActionMessage(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["pointer"]
    request_id: str = Field(min_length=1, max_length=64, pattern=REQUEST_ID_PATTERN)
    action: PointerAction
    dx: int = Field(default=0, ge=-100, le=100)
    dy: int = Field(default=0, ge=-100, le=100)

    @model_validator(mode="after")
    def validate_action_payload(self) -> PointerActionMessage:
        if self.action in {PointerAction.TAP, PointerAction.DOUBLE_TAP} and (self.dx or self.dy):
            raise ValueError("Tap actions do not accept movement values.")
        if self.action is PointerAction.MOVE and not (self.dx or self.dy):
            raise ValueError("Move actions require a non-zero delta.")
        if self.action is PointerAction.SCROLL and (self.dx or not self.dy):
            raise ValueError("Scroll actions require a non-zero vertical delta only.")
        return self


def sanitize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(
        character for character in normalized if not unicodedata.category(character).startswith("C")
    )


class TextInputMessage(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["text_input"]
    request_id: str = Field(min_length=1, max_length=64, pattern=REQUEST_ID_PATTERN)
    text: str = Field(min_length=1, max_length=256)
    submit: bool = Field(default=False, strict=True)

    @field_validator("text", mode="before")
    @classmethod
    def sanitize_text_input(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("Text input must be a string.")
        sanitized = sanitize_text(value)
        if not sanitized.strip():
            raise ValueError("Text input must include visible characters.")
        return sanitized


class SearchVideoMessage(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["search_video"]
    request_id: str = Field(min_length=1, max_length=64, pattern=REQUEST_ID_PATTERN)
    query: str = Field(min_length=1, max_length=128)

    @field_validator("query", mode="before")
    @classmethod
    def sanitize_query(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("Search query must be a string.")
        sanitized = sanitize_text(value).strip()
        if not sanitized:
            raise ValueError("Search query must include visible characters.")
        return sanitized


ClientMessage = Annotated[
    AuthenticationMessage
    | CommandMessage
    | PointerActionMessage
    | TextInputMessage
    | SearchVideoMessage,
    Field(discriminator="type"),
]
client_message_adapter = TypeAdapter(ClientMessage)


class AcknowledgementMessage(WireModel):
    version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    type: Literal["ack"] = "ack"
    request_id: str = Field(min_length=1, max_length=64, pattern=REQUEST_ID_PATTERN)
    success: bool
    error_code: str | None = Field(default=None, max_length=64)
    message: str | None = Field(default=None, max_length=256)


class ErrorMessage(WireModel):
    version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    type: Literal["error"] = "error"
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=256)


class StateMessage(WireModel):
    version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    type: Literal["state"] = "state"
    active_app: str
    focused_tile: str
    volume: int = Field(ge=0, le=100)
    muted: bool
    brightness: int = Field(default=100, ge=10, le=100)
    channel_number: int | None = None
    channel_name: str | None = Field(default=None, max_length=120)
    previous_channel_name: str | None = Field(default=None, max_length=120)
    next_channel_name: str | None = Field(default=None, max_length=120)
    status_message: str | None = Field(default=None, max_length=256)
    error_message: str | None = Field(default=None, max_length=256)
    netflix_context: NetflixContext | None = None
    update_available: str | None = None


def parse_client_message(payload: object) -> ClientMessage:
    return client_message_adapter.validate_python(payload)
