from __future__ import annotations

import json

from app.config import load_settings


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
