from __future__ import annotations

import os
from typing import Any

from app.commands.ports import CommandExecutionError


class WindowsVolumeController:
    def __init__(self, *, step_percent: int = 5, endpoint: Any | None = None) -> None:
        self._step = step_percent / 100
        self._endpoint = endpoint

    async def increase(self) -> tuple[int, bool]:
        return self._adjust(self._step)

    async def decrease(self) -> tuple[int, bool]:
        return self._adjust(-self._step)

    async def toggle_mute(self) -> tuple[int, bool]:
        endpoint = self._get_endpoint()
        muted = not bool(endpoint.GetMute())
        endpoint.SetMute(muted, None)
        return self._read_state(endpoint)

    def _adjust(self, delta: float) -> tuple[int, bool]:
        endpoint = self._get_endpoint()
        current = float(endpoint.GetMasterVolumeLevelScalar())
        endpoint.SetMasterVolumeLevelScalar(min(1.0, max(0.0, current + delta)), None)
        return self._read_state(endpoint)

    def _get_endpoint(self) -> Any:
        if self._endpoint is not None:
            return self._endpoint
        if os.name != "nt":
            raise CommandExecutionError(
                "windows_only", "System volume control is only available on Windows."
            )
        try:
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL, CoInitialize
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            CoInitialize()
            device = AudioUtilities.GetSpeakers()
            self._endpoint = getattr(device, "EndpointVolume", None)
            if self._endpoint is None:
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self._endpoint = cast(interface, POINTER(IAudioEndpointVolume))
            return self._endpoint
        except CommandExecutionError:
            raise
        except Exception as error:
            raise CommandExecutionError(
                "volume_unavailable", "Windows system volume is unavailable."
            ) from error

    @staticmethod
    def _read_state(endpoint: Any) -> tuple[int, bool]:
        level = round(float(endpoint.GetMasterVolumeLevelScalar()) * 100)
        return level, bool(endpoint.GetMute())
