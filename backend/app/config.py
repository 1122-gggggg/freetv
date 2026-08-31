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
    cloudflared_path: str = ""
    browser_path: str = ""


class UrlSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    youtube: str = "https://www.youtube.com/tv"
    netflix: str = "https://www.netflix.com/"
    browser: str = "https://www.google.com/"

    @field_validator("youtube", "browser")
    @classmethod
    def validate_web_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Configured URLs must use http or https and include a host.")
        return value

    @field_validator("netflix")
    @classmethod
    def validate_netflix_url(cls, value: str) -> str:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or (
            host != "netflix.com" and not host.endswith(".netflix.com")
        ):
            raise ValueError("Netflix URL must use https and host netflix.com or a subdomain.")
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
    configured_path: str, candidates: tuple[Path, ...], commands: str | tuple[str, ...]
) -> Path | None:
    if configured_path:
        configured = Path(os.path.expandvars(configured_path)).expanduser()
        if configured.is_file():
            return configured

    command_names = (commands,) if isinstance(commands, str) else commands
    for command in command_names:
        found = shutil.which(command)
        if found:
            return Path(found)

    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _windows_search_roots() -> tuple[Path, Path, Path]:
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    return program_files, program_files_x86, local_app_data


def _chrome_candidates(*, os_name: str = os.name) -> tuple[Path, ...]:
    if os_name == "nt":
        program_files, program_files_x86, local_app_data = _windows_search_roots()
        return (
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
        )
    home = Path.home()
    return (
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/snap/bin/chromium"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        home / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome",
    )


def _brave_candidates(*, os_name: str = os.name) -> tuple[Path, ...]:
    if os_name == "nt":
        program_files, _, local_app_data = _windows_search_roots()
        return (
            program_files / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
            local_app_data / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        )
    return (
        Path("/usr/bin/brave-browser"),
        Path("/usr/bin/brave"),
        Path("/snap/bin/brave"),
        Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    )


def _edge_candidates(*, os_name: str = os.name) -> tuple[Path, ...]:
    if os_name == "nt":
        program_files, program_files_x86, _ = _windows_search_roots()
        return (
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        )
    return (
        Path("/usr/bin/microsoft-edge"),
        Path("/usr/bin/microsoft-edge-stable"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    )


def _mpv_candidates(*, os_name: str = os.name) -> tuple[Path, ...]:
    if os_name == "nt":
        program_files, _, local_app_data = _windows_search_roots()
        return (
            program_files / "mpv" / "mpv.exe",
            local_app_data / "Programs" / "mpv" / "mpv.exe",
            local_app_data / "Microsoft" / "WinGet" / "Links" / "mpv.exe",
        )
    return (
        Path("/usr/bin/mpv"),
        Path("/usr/local/bin/mpv"),
        Path("/opt/homebrew/bin/mpv"),
        Path("/Applications/mpv.app/Contents/MacOS/mpv"),
    )


def resolve_application_paths(
    settings: Settings,
    *,
    os_name: str = os.name,
    root: Path | None = None,
) -> dict[str, Path | None]:
    base = root or project_root()
    bundled_mpv = base / "tools" / "mpv" / "mpv.exe"
    bundled_cloudflared = base / "tools" / "cloudflared" / "cloudflared.exe"
    chrome_commands = (
        ("chrome.exe",)
        if os_name == "nt"
        else ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser", "chrome")
    )
    brave_commands = ("brave.exe",) if os_name == "nt" else ("brave-browser", "brave")
    edge_commands = (
        ("msedge.exe",) if os_name == "nt" else ("microsoft-edge-stable", "microsoft-edge")
    )
    mpv_commands = ("mpv.exe",) if os_name == "nt" else ("mpv",)
    cloudflared_commands = ("cloudflared.exe",) if os_name == "nt" else ("cloudflared",)
    browser_commands = ("msedge.exe",) if os_name == "nt" else ("microsoft-edge", "firefox")
    return {
        "chrome": find_executable(
            settings.applications.chrome_path, _chrome_candidates(os_name=os_name), chrome_commands
        ),
        "brave": find_executable(
            settings.applications.brave_path, _brave_candidates(os_name=os_name), brave_commands
        ),
        "edge": find_executable(
            settings.applications.edge_path, _edge_candidates(os_name=os_name), edge_commands
        ),
        "mpv": find_executable(
            settings.applications.mpv_path,
            (*_mpv_candidates(os_name=os_name), bundled_mpv),
            mpv_commands,
        ),
        "cloudflared": find_executable(
            settings.applications.cloudflared_path,
            (bundled_cloudflared,),
            cloudflared_commands,
        ),
        "browser": find_executable(settings.applications.browser_path, (), browser_commands),
    }


def detect_capabilities(settings: Settings, *, os_name: str = os.name) -> dict[str, bool]:
    applications = resolve_application_paths(settings, os_name=os_name)
    return {
        "chrome_available": applications["chrome"] is not None,
        "brave_available": applications["brave"] is not None,
        "edge_available": applications["edge"] is not None,
        "mpv_available": applications["mpv"] is not None,
    }
