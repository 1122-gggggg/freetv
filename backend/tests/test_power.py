from __future__ import annotations

import asyncio

import pytest

from app.commands.ports import CommandExecutionError
from app.system.power import WindowsPowerController


def test_windows_shutdown_schedules_power_off_after_acknowledgement() -> None:
    calls: list[list[str]] = []
    controller = WindowsPowerController(
        os_name="nt",
        shutdown_runner=lambda arguments: calls.append(list(arguments)),
    )

    asyncio.run(controller.shutdown())

    assert calls == [["shutdown.exe", "/s", "/t", "5"]]


def test_windows_shutdown_rejects_non_windows_hosts() -> None:
    controller = WindowsPowerController(os_name="posix", shutdown_runner=lambda _: None)

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(controller.shutdown())

    assert caught.value.code == "windows_only"
