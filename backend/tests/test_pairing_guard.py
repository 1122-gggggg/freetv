from __future__ import annotations

from app.main import PairingAttemptGuard


def test_pairing_attempt_limit_expires_without_restart() -> None:
    current_time = [0.0]
    guard = PairingAttemptGuard(max_attempts=2, window_seconds=60, clock=lambda: current_time[0])

    guard.record_failure("192.168.1.20")
    guard.record_failure("192.168.1.20")

    assert not guard.may_attempt("192.168.1.20")
    current_time[0] = 61.0
    assert guard.may_attempt("192.168.1.20")


def test_pairing_attempt_limit_starts_a_full_cooldown_after_the_threshold() -> None:
    current_time = [0.0]
    guard = PairingAttemptGuard(max_attempts=5, window_seconds=60, clock=lambda: current_time[0])

    for attempt_time in (0.0, 1.0, 2.0, 3.0, 59.9):
        current_time[0] = attempt_time
        guard.record_failure("192.168.1.20")

    assert not guard.may_attempt("192.168.1.20")
    current_time[0] = 60.1
    assert not guard.may_attempt("192.168.1.20")
    current_time[0] = 120.0
    assert guard.may_attempt("192.168.1.20")
