from __future__ import annotations

import asyncio
import ctypes
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from app.commands.ports import CommandExecutionError
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


def _install_audio_modules(
    monkeypatch: pytest.MonkeyPatch,
    device: object,
) -> tuple[list[str], object]:
    initialized: list[str] = []
    pointer_type = object()

    comtypes = ModuleType("comtypes")
    comtypes.CLSCTX_ALL = "all-contexts"
    comtypes.CoInitialize = lambda: initialized.append("initialized")

    endpoint_volume_type = SimpleNamespace(_iid_="endpoint-volume-iid")
    pycaw_package = ModuleType("pycaw")
    pycaw_package.__path__ = []  # type: ignore[attr-defined]
    pycaw_module = ModuleType("pycaw.pycaw")
    pycaw_module.AudioUtilities = SimpleNamespace(GetSpeakers=lambda: device)
    pycaw_module.IAudioEndpointVolume = endpoint_volume_type

    monkeypatch.setattr("app.system.volume.os.name", "nt")
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setitem(sys.modules, "pycaw", pycaw_package)
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", pycaw_module)
    monkeypatch.setattr(ctypes, "POINTER", lambda _: pointer_type)

    return initialized, pointer_type


def test_volume_uses_endpoint_volume_from_current_pycaw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = FakeEndpoint(level=0.4)

    class CurrentAudioDevice:
        EndpointVolume = endpoint

        def Activate(self, *_: object) -> None:
            raise AssertionError("Activate should not be called when EndpointVolume is available")

    initialized, _ = _install_audio_modules(monkeypatch, CurrentAudioDevice())

    result = asyncio.run(WindowsVolumeController(step_percent=5).increase())

    assert result == (45, False)
    assert endpoint.level == pytest.approx(0.45)
    assert initialized == ["initialized"]


@pytest.mark.parametrize("endpoint_volume", [None, pytest.param("missing", id="missing")])
def test_volume_falls_back_to_activate_for_legacy_pycaw(
    monkeypatch: pytest.MonkeyPatch,
    endpoint_volume: object | None,
) -> None:
    endpoint = FakeEndpoint(level=0.5)
    activation_calls: list[tuple[object, object, object]] = []

    class LegacyAudioDevice:
        def Activate(self, *args: object) -> FakeEndpoint:
            activation_calls.append(args)
            return endpoint

    device = LegacyAudioDevice()
    if endpoint_volume != "missing":
        device.EndpointVolume = endpoint_volume  # type: ignore[attr-defined]
    initialized, pointer_type = _install_audio_modules(monkeypatch, device)
    cast_calls: list[tuple[object, object]] = []

    def fake_cast(interface: object, target_type: object) -> object:
        cast_calls.append((interface, target_type))
        return interface

    monkeypatch.setattr(ctypes, "cast", fake_cast)

    result = asyncio.run(WindowsVolumeController(step_percent=5).decrease())

    assert result == (45, False)
    assert activation_calls == [("endpoint-volume-iid", "all-contexts", None)]
    assert cast_calls == [(endpoint, pointer_type)]
    assert initialized == ["initialized"]


def test_volume_wraps_pycaw_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    class UnavailableAudioDevice:
        EndpointVolume = None

        def Activate(self, *_: object) -> None:
            raise OSError("audio endpoint is unavailable")

    _install_audio_modules(monkeypatch, UnavailableAudioDevice())

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(WindowsVolumeController().increase())

    assert caught.value.code == "volume_unavailable"
    assert caught.value.message == "無法使用 Windows 系統音量。"
    assert isinstance(caught.value.__cause__, OSError)


def test_volume_preserves_existing_command_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = CommandExecutionError("audio_policy_denied", "Audio policy denied access.")

    class FailingAudioDevice:
        @property
        def EndpointVolume(self) -> Any:
            raise expected

    _install_audio_modules(monkeypatch, FailingAudioDevice())

    with pytest.raises(CommandExecutionError) as caught:
        asyncio.run(WindowsVolumeController().increase())

    assert caught.value is expected
