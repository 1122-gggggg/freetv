from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.security.request_limits import BoundedPairingRequestBodyMiddleware


class DownstreamApplication:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.calls += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def test_pairing_request_limit_rejects_chunked_oversize_before_reaching_the_app() -> None:
    async def scenario() -> None:
        downstream = DownstreamApplication()
        middleware = BoundedPairingRequestBodyMiddleware(downstream, max_body_bytes=8)
        messages = iter(
            [
                {"type": "http.request", "body": b"1234", "more_body": True},
                {"type": "http.request", "body": b"56789", "more_body": False},
            ]
        )
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return next(messages)

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await middleware({"type": "http", "path": "/api/pair", "headers": []}, receive, send)

        assert downstream.calls == 0
        assert sent[0]["status"] == 413

    asyncio.run(scenario())


def test_pairing_request_limit_times_out_before_reaching_the_app() -> None:
    async def scenario() -> None:
        downstream = DownstreamApplication()
        middleware = BoundedPairingRequestBodyMiddleware(
            downstream, max_body_bytes=8, read_timeout_seconds=0.001
        )
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            await asyncio.sleep(0.01)
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await middleware({"type": "http", "path": "/api/pair", "headers": []}, receive, send)

        assert downstream.calls == 0
        assert sent[0]["status"] == 408

    asyncio.run(scenario())
