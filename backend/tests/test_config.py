from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app import config
from app.config import (
    ApplicationSettings,
    Settings,
    UrlSettings,
    detect_capabilities,
    find_executable,
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
    assert settings.urls.youtube == "https://www.youtube.com/tv"
    assert settings.urls.browser == "https://example.test/"


def test_load_settings_rejects_non_web_browser_urls(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"urls": {"browser": "file:///C:/Windows/System32/cmd.exe"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="http or https"):
        load_settings(settings_path)


@pytest.mark.parametrize(
    "netflix_url",
    [
        "http://www.netflix.com/",
        "https://netflix.com.evil.test/",
        "https://evilnetflix.com/",
        "https://example.test/",
    ],
)
def test_netflix_url_requires_https_netflix_host(netflix_url: str) -> None:
    with pytest.raises(ValidationError, match="Netflix"):
        UrlSettings(netflix=netflix_url)


@pytest.mark.parametrize(
    "netflix_url",
    [
        "https://netflix.com/",
        "https://www.netflix.com/login",
        "https://help.netflix.com/",
    ],
)
def test_netflix_url_accepts_exact_host_and_subdomains(netflix_url: str) -> None:
    assert UrlSettings(netflix=netflix_url).netflix == netflix_url


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


def test_resolve_application_paths_finds_winget_mpv(tmp_path, monkeypatch) -> None:
    mpv_exe = tmp_path / "Microsoft" / "WinGet" / "Links" / "mpv.exe"
    mpv_exe.parent.mkdir(parents=True)
    mpv_exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "Program Files (x86)"))
    monkeypatch.delenv("PATH", raising=False)

    paths = resolve_application_paths(Settings(), os_name="nt")
    assert paths["mpv"] == mpv_exe


def test_resolve_application_paths_prefers_system_mpv_over_bundle(
    tmp_path, monkeypatch
) -> None:
    bundled = tmp_path / "tools" / "mpv" / "mpv.exe"
    bundled.parent.mkdir(parents=True)
    bundled.touch()
    system = tmp_path / "system" / "mpv.exe"
    system.parent.mkdir()
    system.touch()
    monkeypatch.setattr(
        config.shutil,
        "which",
        lambda name: str(system) if name == "mpv.exe" else None,
    )

    paths = resolve_application_paths(Settings(), os_name="nt", root=tmp_path)

    assert paths["mpv"] == system


def test_resolve_application_paths_falls_back_to_bundled_tools(
    tmp_path, monkeypatch
) -> None:
    mpv = tmp_path / "tools" / "mpv" / "mpv.exe"
    cloudflared = tmp_path / "tools" / "cloudflared" / "cloudflared.exe"
    for executable in (mpv, cloudflared):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch()
    monkeypatch.setattr(config.shutil, "which", lambda _: None)

    paths = resolve_application_paths(Settings(), os_name="nt", root=tmp_path)

    assert paths["mpv"] == mpv
    assert paths["cloudflared"] == cloudflared


def test_resolve_application_paths_ignores_bundled_windows_tools_on_non_windows(
    tmp_path, monkeypatch
) -> None:
    bundled_mpv = tmp_path / "tools" / "mpv" / "mpv.exe"
    bundled_cloudflared = tmp_path / "tools" / "cloudflared" / "cloudflared.exe"
    for executable in (bundled_mpv, bundled_cloudflared):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch()
    monkeypatch.setattr(config.shutil, "which", lambda _: None)

    paths = resolve_application_paths(Settings(), os_name="posix", root=tmp_path)

    assert paths["mpv"] != bundled_mpv
    assert paths["cloudflared"] != bundled_cloudflared


def test_find_executable_accepts_multiple_command_names(tmp_path, monkeypatch) -> None:
    chrome = tmp_path / "google-chrome"
    chrome.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "app.config.shutil.which",
        lambda command: str(chrome) if command == "google-chrome-stable" else None,
    )

    found = find_executable("", (), ("google-chrome-stable", "chromium"))
    assert found == chrome
