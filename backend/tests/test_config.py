from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.config import (
    ApplicationSettings,
    Settings,
    detect_capabilities,
    load_settings,
    resolve_application_paths,
)
from app.controller import build_runtime

def test_load_settings_merges_defaults_with_local_overrides(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "server": {"port": 9999},
                "applications": {"brave_path": "C:/Tools/Brave/brave.exe"},
                "urls": {"browser": "https://example.test/"},
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(settings_path)

    assert settings.server.host == "0.0.0.0"
    assert settings.server.port == 9999
    assert settings.applications.brave_path == "C:/Tools/Brave/brave.exe"
    assert settings.urls.youtube == "https://www.youtube.com/"
    assert settings.urls.browser == "https://example.test/"


def test_load_settings_rejects_non_web_browser_urls(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"urls": {"browser": "file:///C:/Windows/System32/cmd.exe"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="http or https"):
        load_settings(settings_path)


def test_runtime_uses_configured_pairing_code_expiry() -> None:
    runtime = build_runtime(Settings(security={"pairing_code_ttl_seconds": 60}))

    _, expires_at = runtime.pairing.current_code()
    remaining_seconds = (expires_at - datetime.now(UTC)).total_seconds()

    assert 55 <= remaining_seconds <= 61


def test_load_settings_supports_chrome_path(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "applications": {"chrome_path": "C:/Tools/Chrome/chrome.exe"},
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(settings_path)
    assert settings.applications.chrome_path == "C:/Tools/Chrome/chrome.exe"


def test_resolve_application_paths_uses_configured_chrome_path(tmp_path) -> None:
    chrome_exe = tmp_path / "chrome.exe"
    chrome_exe.write_text("", encoding="utf-8")
    settings = Settings(applications=ApplicationSettings(chrome_path=str(chrome_exe)))

    paths = resolve_application_paths(settings)
    assert paths["chrome"] == chrome_exe


def test_detect_capabilities_reports_chrome_availability(tmp_path) -> None:
    chrome_exe = tmp_path / "chrome.exe"
    chrome_exe.write_text("", encoding="utf-8")
    settings = Settings(applications=ApplicationSettings(chrome_path=str(chrome_exe)))

    capabilities = detect_capabilities(settings)
    assert capabilities["chrome_available"] is True
