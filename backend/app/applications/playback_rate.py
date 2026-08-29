from __future__ import annotations

PLAYBACK_RATE_STEPS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)


def next_playback_rate(current: float, direction: int) -> float:
    step = 1 if direction > 0 else -1
    index = 2
    for offset, rate in enumerate(PLAYBACK_RATE_STEPS):
        if abs(rate - current) < 0.01:
            index = offset
            break
    return PLAYBACK_RATE_STEPS[max(0, min(len(PLAYBACK_RATE_STEPS) - 1, index + step))]


def format_playback_rate(rate: float) -> str:
    return f"{rate:.2f}".rstrip("0").rstrip(".")
