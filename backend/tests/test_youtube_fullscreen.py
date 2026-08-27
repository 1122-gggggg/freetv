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
    extract_video_identity,
)


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
def test_extract_video_identity_covers_supported_routes(
    url: str, identity: str | None
) -> None:
    assert extract_video_identity(url) == identity


@dataclass
class FakeProbe:
    inspections: list[tuple[str | None, bool, bool]] = field(
        default_factory=lambda: [("watch:alpha", True, False)]
    )
    fullscreen_calls: list[tuple[int, str, bool]] = field(default_factory=list)
    fail_after_send: bool = False

    async def inspect(self, port: int) -> tuple[str | None, bool, bool]:
        assert port == 9222
        if len(self.inspections) == 1:
            return self.inspections[0]
        return self.inspections.pop(0)

    async def fullscreen(self, port: int, video_id: str, user_gesture: bool) -> None:
        self.fullscreen_calls.append((port, video_id, user_gesture))
        if self.fail_after_send:
            raise TimeoutError


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

    async def fullscreen(self, port: int, video_id: str, user_gesture: bool) -> None:
        raise AssertionError("fullscreen must not be reached")


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
        result: dict[str, object] = {
            "result": {"type": "object", "value": self.value}
        }
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
    connect.contexts = [
        FakeSocketContext(FakeSocket(inspection, outer_exception=True))
    ]
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
        controller = YoutubeFullscreenController(
            probe=ShortCdpYoutubeProbe(timeout=0.8)
        )
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
