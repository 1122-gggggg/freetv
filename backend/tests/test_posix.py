from __future__ import annotations

import asyncio

import pytest

from app.commands.ports import CommandExecutionError
from app.protocol import Command, PointerAction, PointerActionMessage
from app.system.posix import (
    PosixInputController,
    PosixPowerController,
    PosixVolumeController,
    PosixWindowController,
)


def _lookup(*available: str):
    def match(*names: str) -> str | None:
        for name in names:
            if name in available:
                return name
        return None

    return match


def test_posix_input_sends_xdotool_keys() -> None:
    calls: list[list[str]] = []
    controller = PosixInputController(
        runner=lambda arguments: calls.append(list(arguments)) or "",
        lookup=_lookup("xdotool"),
    )

    controller.send_command(Command.NAV_UP)
    controller.send_browser_back()
    asyncio.run(
        controller.pointer(
            PointerActionMessage(
                version=1,
                type="pointer",
                request_id="move-1",
                action=PointerAction.MOVE,
                dx=-3,
                dy=4,
            )
        )
    )

    assert calls == [
        ["xdotool", "key", "Up"],
        ["xdotool", "key", "alt+Left"],
        ["xdotool", "mousemove_relative", "--", "-3", "4"],
    ]


def test_posix_volume_uses_wpctl_relative_steps() -> None:
    calls: list[list[str]] = []

    def runner(arguments: list[str]) -> str:
        calls.append(list(arguments))
        if arguments[:2] == ["wpctl", "get-volume"]:
            return "Volume: 0.40 [MUTED]\n"
        return ""

    controller = PosixVolumeController(runner=runner, lookup=_lookup("wpctl"))
    level, muted = asyncio.run(controller.decrease())

    assert level == 40
    assert muted is True
    assert ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-", "-l", "1.0"] in calls


def test_posix_power_uses_systemctl_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("app.system.posix.sys.platform", "linux")
    controller = PosixPowerController(
        runner=lambda arguments: calls.append(list(arguments)) or "",
        lookup=_lookup("systemctl"),
    )

    asyncio.run(controller.sleep())

    assert calls == [["systemctl", "suspend"]]


def test_posix_window_uses_pid_as_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.system.posix.pid_is_running", lambda pid: pid == 4242)
    windows = PosixWindowController(lookup=_lookup())

    assert windows.find_window_for_pid(4242, 0) == 4242
    assert windows.window_belongs_to_process(4242, 4242) is True
    assert windows.find_window_for_pid(7, 0) is None


def test_posix_input_errors_without_backend() -> None:
    controller = PosixInputController(runner=lambda arguments: "", lookup=_lookup())
    with pytest.raises(CommandExecutionError) as caught:
        controller.send_command(Command.OK)
    assert caught.value.code == "input_unavailable"
