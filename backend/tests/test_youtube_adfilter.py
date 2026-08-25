from __future__ import annotations

from app.applications.youtube_adfilter import (
    BLOCKED_URL_PATTERNS,
    SKIP_ADS_SCRIPT,
    reserve_localhost_port,
)


def test_blocked_patterns_cover_youtube_and_doubleclick() -> None:
    joined = " ".join(BLOCKED_URL_PATTERNS)
    assert "doubleclick.net" in joined
    assert "pagead" in joined
    assert "ptracking" in joined
    assert "api/stats/ads" in joined


def test_skip_script_clicks_skip_and_hides_slots() -> None:
    assert ".ytp-ad-skip-button" in SKIP_ADS_SCRIPT
    assert "ytd-ad-slot-renderer" in SKIP_ADS_SCRIPT
    assert "playbackRate = 16" in SKIP_ADS_SCRIPT
    assert "__pcTvAdFilter" in SKIP_ADS_SCRIPT


def test_reserve_localhost_port_returns_bindable_port() -> None:
    port = reserve_localhost_port()
    assert 0 < port < 65536
