from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = Field(default=8765, ge=1, le=65535)
    transport: Literal["http", "https"] = "http"


class ApplicationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chrome_path: str = ""
    brave_path: str = ""
    edge_path: str = ""
    mpv_path: str = ""
    browser_path: str = ""

class UrlSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    youtube: str = "https://www.youtube.com/tv"
    netflix: str = "https://www.netflix.com/"
    browser: str = "https://www.google.com/"

    @field_validator("youtube", "netflix", "browser")
    @classmethod
    def validate_web_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Configured URLs must use http or https and include a host.")
        return value


class SecuritySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pairing_code_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    remote_token_bytes: int = Field(default=32, ge=24, le=64)
    remote_token_ttl_days: int = Field(default=90, ge=1, le=365)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerSettings = Field(default_factory=ServerSettings)
    applications: ApplicationSettings = Field(default_factory=ApplicationSettings)
    urls: UrlSettings = Field(default_factory=UrlSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_settings_path() -> Path:
    return project_root() / "config" / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    settings_path = path or default_settings_path()
    if not settings_path.exists():
        return Settings()

    raw: Any = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Settings JSON must contain an object.")
    return Settings.model_validate(raw)


def find_executable(
    configured_path: str, candidates: tuple[Path, ...], command: str
) -> Path | None:
    if configured_path:
        configured = Path(os.path.expandvars(configured_path)).expanduser()
        if configured.is_file():
            return configured

    found = shutil.which(command)
    if found:
        return Path(found)

    return next((candidate for candidate in candidates if candidate.is_file()), None)


def resolve_application_paths(settings: Settings) -> dict[str, Path | None]:
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))

    return {
        "chrome": find_executable(
            settings.applications.chrome_path,
            (
                program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
                program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
                local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
            ),
            "chrome.exe",
        ),
        "brave": find_executable(
            settings.applications.brave_path,
            (
                program_files / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
                local_app_data / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
            ),
            "brave.exe",
        ),
        "edge": find_executable(
            settings.applications.edge_path,
            (
                program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ),
            "msedge.exe",
        ),
        "mpv": find_executable(
            settings.applications.mpv_path,
            (
                program_files / "mpv" / "mpv.exe",
                local_app_data / "Programs" / "mpv" / "mpv.exe",
                local_app_data / "Microsoft" / "WinGet" / "Links" / "mpv.exe",
            ),
            "mpv.exe",
        ),
        "browser": find_executable(settings.applications.browser_path, (), "browser.exe"),
    }


def detect_capabilities(settings: Settings) -> dict[str, bool]:
    applications = resolve_application_paths(settings)
    return {
        "chrome_available": applications["chrome"] is not None,
        "brave_available": applications["brave"] is not None,
        "edge_available": applications["edge"] is not None,
        "mpv_available": applications["mpv"] is not None,
    }
