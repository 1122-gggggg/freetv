from __future__ import annotations

from app.applications.playback_rate import format_playback_rate, next_playback_rate


def test_playback_rate_steps_up_and_down_from_one() -> None:
    assert next_playback_rate(1.0, 1) == 1.25
    assert next_playback_rate(1.25, -1) == 1.0
    assert next_playback_rate(2.0, 1) == 2.0
    assert next_playback_rate(0.5, -1) == 0.5
    assert next_playback_rate(1.13, 1) == 1.25


def test_format_playback_rate_drops_trailing_zeros() -> None:
    assert format_playback_rate(1.0) == "1"
    assert format_playback_rate(1.25) == "1.25"
    assert format_playback_rate(2.0) == "2"
