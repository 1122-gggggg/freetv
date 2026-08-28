from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.applications import youtube_fullscreen as fullscreen_module
from app.applications.youtube_fullscreen import (
    ShortCdpYoutubeProbe,
    YoutubeFullscreenController,
    _fullscreen_expression,
    extract_video_identity,
)
from app.commands.ports import CommandExecutionError


@pytest.mark.parametrize(
    ("url", "identity"),
    [
        ("https://www.youtube.com/watch?v=alpha", "watch:alpha"),
        ("https://www.youtube.com/tv#/watch?v=beta", "watch:beta"),
        ("https://www.youtube.com/shorts/gamma?feature=share", "shorts:gamma"),
        ("https://www.youtube.com/live/delta", "live:delta"),
        ("https://www.youtube.com/tv#/browse", None),
        ("https://example.com/watch?v=alpha", None),
    ],
)
def test_extract_video_identity_covers_supported_routes(url: str, identity: str | None) -> None:
    assert extract_video_identity(url) == identity


@dataclass
class FakeProbe:
    inspections: list[tuple[str | None, bool, bool]] = field(
        default_factory=lambda: [("watch:alpha", True, False)]
    )
    fullscreen_calls: list[tuple[int, str, bool]] = field(default_factory=list)
    fullscreen_result: bool = True
    fail_after_send: bool = False
    rate_calls: list[tuple[int, int]] = field(default_factory=list)
    rate_result: float = 1.25
    seek_calls: list[tuple[int, int]] = field(default_factory=list)
    seek_result: bool = True

    async def inspect(self, port: int) -> tuple[str | None, bool, bool]:
        assert port == 9222
        if len(self.inspections) == 1:
            return self.inspections[0]
        return self.inspections.pop(0)

    async def fullscreen(self, port: int, video_id: str, user_gesture: bool) -> bool:
        self.fullscreen_calls.append((port, video_id, user_gesture))
        if self.fail_after_send:
            raise TimeoutError
        return self.fullscreen_result

    async def playback_rate(self, port: int, direction: int) -> float:
        self.rate_calls.append((port, direction))
        return self.rate_result

    async def seek(self, port: int, direction: int) -> bool:
        self.seek_calls.append((port, direction))
        return self.seek_result


@pytest.mark.parametrize(
    "inspection",
    [
        (None, True, False),
        ("watch:alpha", False, False),
        ("watch:alpha", True, True),
    ],
)
def test_probe_requires_video_ready_and_not_already_fullscreen(
    inspection: tuple[str | None, bool, bool],
) -> None:
    async def scenario() -> tuple[bool, list[tuple[int, str, bool]]]:
        probe = FakeProbe(inspections=[inspection])
        result = await YoutubeFullscreenController(probe=probe).probe_once(9222)
        return result, probe.fullscreen_calls

    assert asyncio.run(scenario()) == (False, [])


def test_same_video_is_requested_at_most_once_even_after_escape() -> None:
    async def scenario() -> tuple[list[bool], list[tuple[int, str, bool]]]:
        probe = FakeProbe(
            inspections=[
                ("watch:alpha", True, False),
                ("watch:alpha", True, False),
            ]
        )
        controller = YoutubeFullscreenController(probe=probe)
        results = [await controller.probe_once(9222), await controller.probe_once(9222)]
        return results, probe.fullscreen_calls

    assert asyncio.run(scenario()) == (
        [True, False],
        [(9222, "watch:alpha", True)],
    )


def test_marks_video_before_send_and_never_retries_unknown_outcome() -> None:
    async def scenario() -> list[tuple[int, str, bool]]:
        probe = FakeProbe(fail_after_send=True)
        controller = YoutubeFullscreenController(probe=probe)
        with pytest.raises(TimeoutError):
            await controller.probe_once(9222)
        assert await controller.probe_once(9222) is False
        return probe.fullscreen_calls

    assert asyncio.run(scenario()) == [(9222, "watch:alpha", True)]


def test_force_fullscreen_ignores_last_identity_once_and_updates_it() -> None:
    async def scenario() -> tuple[bool, bool, list[tuple[int, str, bool]]]:
        probe = FakeProbe(
            inspections=[
                ("watch:alpha", True, False),
                ("watch:alpha", True, False),
            ]
        )
        controller = YoutubeFullscreenController(probe=probe)
        assert await controller.probe_once(9222)

        forced = await controller.force_fullscreen(9222)
        automatic_after_force = await controller.probe_once(9222)
        return forced, automatic_after_force, probe.fullscreen_calls

    assert asyncio.run(scenario()) == (
        True,
        False,
        [
            (9222, "watch:alpha", True),
            (9222, "watch:alpha", True),
        ],
    )


def test_force_fullscreen_rejects_missing_or_unready_video() -> None:
    async def scenario(inspection: tuple[str | None, bool, bool]) -> str:
        controller = YoutubeFullscreenController(probe=FakeProbe(inspections=[inspection]))
        with pytest.raises(CommandExecutionError) as caught:
            await controller.force_fullscreen(9222)
        return caught.value.code

    assert asyncio.run(scenario((None, True, False))) == "youtube_video_unavailable"
    assert asyncio.run(scenario(("watch:alpha", False, False))) == "youtube_video_unavailable"


def test_force_fullscreen_unknown_outcome_sends_only_once() -> None:
    async def scenario() -> list[tuple[int, str, bool]]:
        probe = FakeProbe(fail_after_send=True)
        controller = YoutubeFullscreenController(probe=probe)
        with pytest.raises(TimeoutError):
            await controller.force_fullscreen(9222)
        return probe.fullscreen_calls

    assert asyncio.run(scenario()) == [(9222, "watch:alpha", True)]


def test_adjust_playback_rate_delegates_to_probe() -> None:
    async def scenario() -> tuple[float, float, list[tuple[int, int]]]:
        probe = FakeProbe()
        controller = YoutubeFullscreenController(probe=probe)
        faster = await controller.adjust_playback_rate(9222, 1)
        probe.rate_result = 0.75
        slower = await controller.adjust_playback_rate(9222, -1)
        return faster, slower, probe.rate_calls

    assert asyncio.run(scenario()) == (1.25, 0.75, [(9222, 1), (9222, -1)])


def test_seek_delegates_to_probe() -> None:
    async def scenario() -> list[tuple[int, int]]:
        probe = FakeProbe()
        controller = YoutubeFullscreenController(probe=probe)
        await controller.seek(9222, -1)
        await controller.seek(9222, 1)
        return probe.seek_calls

    assert asyncio.run(scenario()) == [(9222, -1), (9222, 1)]


@dataclass
class CoalescingProbe:
    inspections: list[tuple[str | None, bool, bool]] = field(
        default_factory=lambda: [
            ("watch:alpha", True, False),
            ("watch:alpha", True, True),
        ]
    )
    fullscreen_calls: list[tuple[int, str, bool]] = field(default_factory=list)
    fullscreen_started: asyncio.Event = field(default_factory=asyncio.Event)
    release_fullscreen: asyncio.Event = field(default_factory=asyncio.Event)

    async def inspect(self, port: int) -> tuple[str | None, bool, bool]:
        assert port == 9222
        return self.inspections.pop(0)

    async def fullscreen(self, port: int, video_id: str, user_gesture: bool) -> bool:
        self.fullscreen_calls.append((port, video_id, user_gesture))
        self.fullscreen_started.set()
        await self.release_fullscreen.wait()
        return True

    async def playback_rate(self, port: int, direction: int) -> float:
        raise AssertionError("playback rate must not be reached")

    async def seek(self, port: int, direction: int) -> bool:
        raise AssertionError("seek must not be reached")


def test_auto_and_manual_fullscreen_coalesce_without_duplicate_request() -> None:
    async def scenario() -> tuple[bool, bool, list[tuple[int, str, bool]]]:
        probe = CoalescingProbe()
        controller = YoutubeFullscreenController(probe=probe)
        automatic = asyncio.create_task(controller.probe_once(9222))
        await probe.fullscreen_started.wait()
        forced = asyncio.create_task(controller.force_fullscreen(9222))
        await asyncio.sleep(0)
        assert probe.fullscreen_calls == [(9222, "watch:alpha", True)]
        probe.release_fullscreen.set()
        return await automatic, await forced, probe.fullscreen_calls

    assert asyncio.run(scenario()) == (
        True,
        False,
        [(9222, "watch:alpha", True)],
    )


def test_force_fullscreen_rejects_second_session_identity_change() -> None:
    async def scenario() -> str:
        controller = YoutubeFullscreenController(probe=FakeProbe(fullscreen_result=False))
        with pytest.raises(CommandExecutionError) as caught:
            await controller.force_fullscreen(9222)
        return caught.value.code

    assert asyncio.run(scenario()) == "youtube_video_unavailable"


@dataclass
class BlockingProbe:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    cancellations: int = 0

    async def inspect(self, port: int) -> tuple[str | None, bool, bool]:
        assert port == 9222
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancellations += 1
            raise
        raise AssertionError("unreachable")

    async def fullscreen(self, port: int, video_id: str, user_gesture: bool) -> bool:
        raise AssertionError("fullscreen must not be reached")

    async def playback_rate(self, port: int, direction: int) -> float:
        raise AssertionError("playback rate must not be reached")

    async def seek(self, port: int, direction: int) -> bool:
        raise AssertionError("seek must not be reached")


def test_start_and_stop_are_idempotent_and_stop_waits_for_the_task() -> None:
    async def scenario() -> tuple[int, bool]:
        probe = BlockingProbe()
        controller = YoutubeFullscreenController(interval_seconds=1.0, probe=probe)
        await controller.start(9222)
        await probe.entered.wait()
        await controller.start(9222)
        await controller.stop()
        await controller.stop()
        return probe.cancellations, probe.entered.is_set()

    assert asyncio.run(scenario()) == (1, True)


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class FakeAsyncClient:
    payload: object = []
    urls: list[str] = []
    exits: int = 0

    def __init__(self, *, timeout: float) -> None:
        assert timeout == 0.8

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        type(self).exits += 1

    async def get(self, url: str) -> FakeResponse:
        type(self).urls.append(url)
        return FakeResponse(type(self).payload)


class FakeSocket:
    def __init__(self, value: object, *, outer_exception: bool = False) -> None:
        self.value = value
        self.outer_exception = outer_exception
        self.requests: list[dict[str, Any]] = []

    async def send(self, request: str) -> None:
        self.requests.append(json.loads(request))

    async def recv(self) -> str:
        request = self.requests[-1]
        result: dict[str, object] = {"result": {"type": "object", "value": self.value}}
        if self.outer_exception:
            result["exceptionDetails"] = {"text": "unsafe evaluation failed"}
        return json.dumps({"id": request["id"], "result": result})


class FakeSocketContext:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> FakeSocket:
        self.entered = True
        return self.socket

    async def __aexit__(self, *_args: object) -> None:
        self.exited = True


class FakeConnect:
    def __init__(self) -> None:
        self.contexts = [
            FakeSocketContext(
                FakeSocket(
                    {
                        "url": "https://www.youtube.com/watch?v=alpha",
                        "ready": True,
                        "fullscreen": False,
                    }
                )
            ),
            FakeSocketContext(FakeSocket(True)),
        ]
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, url: str, **kwargs: object) -> FakeSocketContext:
        self.calls.append((url, kwargs))
        return self.contexts[len(self.calls) - 1]


def _youtube_target(debugger_url: str) -> dict[str, object]:
    return {
        "type": "page",
        "url": "https://www.youtube.com/watch?v=alpha",
        "webSocketDebuggerUrl": debugger_url,
    }


def test_short_cdp_probe_uses_localhost_and_closes_each_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.payload = [_youtube_target("ws://127.0.0.1:9222/devtools/page/alpha")]
    FakeAsyncClient.urls = []
    FakeAsyncClient.exits = 0
    connect = FakeConnect()
    monkeypatch.setattr(fullscreen_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(fullscreen_module.websockets, "connect", connect)

    async def scenario() -> bool:
        probe = ShortCdpYoutubeProbe(timeout=0.8)
        controller = YoutubeFullscreenController(probe=probe)
        return await controller.probe_once(9222)

    assert asyncio.run(scenario()) is True
    assert FakeAsyncClient.urls == [
        "http://127.0.0.1:9222/json/list",
        "http://127.0.0.1:9222/json/list",
    ]
    assert FakeAsyncClient.exits == 2
    assert [url for url, _ in connect.calls] == [
        "ws://127.0.0.1:9222/devtools/page/alpha",
        "ws://127.0.0.1:9222/devtools/page/alpha",
    ]
    assert all(context.entered and context.exited for context in connect.contexts)

    inspect_request = connect.contexts[0].socket.requests[0]
    assert inspect_request["method"] == "Runtime.evaluate"
    assert "readyState >= 2" in inspect_request["params"]["expression"]
    assert "document.fullscreenElement" in inspect_request["params"]["expression"]
    assert "userGesture" not in inspect_request["params"]

    fullscreen_request = connect.contexts[1].socket.requests[0]
    assert fullscreen_request["method"] == "Runtime.evaluate"
    assert fullscreen_request["params"]["userGesture"] is True
    expression = fullscreen_request["params"]["expression"]
    assert expression.count("requestFullscreen") == 1
    assert "click(" not in expression
    assert "key" not in expression.lower()


def test_short_cdp_probe_sets_playback_rate_with_user_gesture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.payload = [_youtube_target("ws://127.0.0.1:9222/devtools/page/alpha")]
    connect = FakeConnect()
    connect.contexts = [FakeSocketContext(FakeSocket(1.25))]
    monkeypatch.setattr(fullscreen_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(fullscreen_module.websockets, "connect", connect)

    rate = asyncio.run(ShortCdpYoutubeProbe(timeout=0.8).playback_rate(9222, 1))

    assert rate == 1.25
    request = connect.contexts[0].socket.requests[0]
    assert request["params"]["userGesture"] is True
    expression = request["params"]["expression"]
    assert "video.playbackRate = next" in expression
    assert "[0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]" in expression


def test_short_cdp_probe_seeks_five_seconds_with_user_gesture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.payload = [_youtube_target("ws://127.0.0.1:9222/devtools/page/alpha")]
    connect = FakeConnect()
    connect.contexts = [FakeSocketContext(FakeSocket(True))]
    monkeypatch.setattr(fullscreen_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(fullscreen_module.websockets, "connect", connect)

    performed = asyncio.run(ShortCdpYoutubeProbe(timeout=0.8).seek(9222, -1))

    assert performed
    request = connect.contexts[0].socket.requests[0]
    assert request["params"]["userGesture"] is True
    expression = request["params"]["expression"]
    assert "video.currentTime + -5" in expression
    assert "video.currentTime = target" in expression


def test_inspect_rejects_outer_runtime_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspection = {
        "url": "https://www.youtube.com/watch?v=alpha",
        "ready": True,
        "fullscreen": False,
    }
    FakeAsyncClient.payload = [_youtube_target("ws://127.0.0.1:9222/devtools/page/alpha")]
    connect = FakeConnect()
    connect.contexts = [FakeSocketContext(FakeSocket(inspection, outer_exception=True))]
    monkeypatch.setattr(fullscreen_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(fullscreen_module.websockets, "connect", connect)

    with pytest.raises(ValueError, match="Runtime.evaluate"):
        asyncio.run(ShortCdpYoutubeProbe(timeout=0.8).inspect(9222))
    assert connect.contexts[0].exited


def test_fullscreen_outer_runtime_exception_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspection = {
        "url": "https://www.youtube.com/watch?v=alpha",
        "ready": True,
        "fullscreen": False,
    }
    FakeAsyncClient.payload = [_youtube_target("ws://127.0.0.1:9222/devtools/page/alpha")]
    connect = FakeConnect()
    connect.contexts = [
        FakeSocketContext(FakeSocket(inspection)),
        FakeSocketContext(FakeSocket(True, outer_exception=True)),
        FakeSocketContext(FakeSocket(inspection)),
    ]
    monkeypatch.setattr(fullscreen_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(fullscreen_module.websockets, "connect", connect)

    async def scenario() -> bool:
        controller = YoutubeFullscreenController(probe=ShortCdpYoutubeProbe(timeout=0.8))
        with pytest.raises(ValueError, match="Runtime.evaluate"):
            await controller.probe_once(9222)
        return await controller.probe_once(9222)

    assert asyncio.run(scenario()) is False
    fullscreen_requests = [
        request
        for context in connect.contexts
        for request in context.socket.requests
        if "requestFullscreen" in request["params"]["expression"]
    ]
    assert len(fullscreen_requests) == 1
    assert all(context.exited for context in connect.contexts)


def test_short_cdp_fullscreen_revalidates_expected_identity_in_second_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.payload = [_youtube_target("ws://127.0.0.1:9222/devtools/page/alpha")]
    connect = FakeConnect()
    connect.contexts = [FakeSocketContext(FakeSocket(False))]
    monkeypatch.setattr(fullscreen_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(fullscreen_module.websockets, "connect", connect)

    result = asyncio.run(
        ShortCdpYoutubeProbe(timeout=0.8).fullscreen(
            9222,
            'watch:alpha";globalThis.pwned=true;//',
            True,
        )
    )

    assert result is False
    request = connect.contexts[0].socket.requests[0]
    expression = request["params"]["expression"]
    assert request["params"]["userGesture"] is True
    assert json.dumps('watch:alpha";globalThis.pwned=true;//') in expression
    assert expression.count("requestFullscreen") == 1


def test_fullscreen_expression_rejects_non_youtube_watch_host() -> None:
    expression = _fullscreen_expression("watch:same")

    assert "url.hostname === 'youtube.com'" in expression
    assert "url.hostname.endsWith('.youtube.com')" in expression
    assert expression.index("url.hostname") < expression.index("requestFullscreen")


@pytest.mark.parametrize(
    "payload",
    [
        [_youtube_target("ws://192.168.1.5:9222/devtools/page/alpha")],
        [
            _youtube_target("ws://127.0.0.1:9222/devtools/page/alpha"),
            _youtube_target("ws://127.0.0.1:9222/devtools/page/beta"),
        ],
        [
            {
                **_youtube_target("ws://127.0.0.1:9222/devtools/page/alpha"),
                "openerId": "popup",
            }
        ],
    ],
)
def test_short_cdp_probe_rejects_nonlocal_or_nonunique_top_level_targets(
    monkeypatch: pytest.MonkeyPatch,
    payload: list[dict[str, object]],
) -> None:
    FakeAsyncClient.payload = payload
    FakeAsyncClient.urls = []
    FakeAsyncClient.exits = 0
    monkeypatch.setattr(fullscreen_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        fullscreen_module.websockets,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not connect")),
    )

    with pytest.raises(ValueError):
        asyncio.run(ShortCdpYoutubeProbe(timeout=0.8).inspect(9222))
