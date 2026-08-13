from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.system.volume import WindowsVolumeController


@dataclass
class FakeEndpoint:
    level: float = 0.98
    muted: bool = False

    def GetMasterVolumeLevelScalar(self) -> float:
        return self.level

    def SetMasterVolumeLevelScalar(self, value: float, _: object) -> None:
        self.level = value

    def GetMute(self) -> bool:
        return self.muted

    def SetMute(self, value: bool, _: object) -> None:
        self.muted = value


def test_volume_is_clamped_and_mute_state_is_synchronized() -> None:
    async def scenario() -> None:
        endpoint = FakeEndpoint()
        controller = WindowsVolumeController(step_percent=5, endpoint=endpoint)

        raised, muted_before = await controller.increase()
        same_level, muted_after = await controller.toggle_mute()

        assert (raised, muted_before) == (100, False)
        assert (same_level, muted_after) == (100, True)

    asyncio.run(scenario())
