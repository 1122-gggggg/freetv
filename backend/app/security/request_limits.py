from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias

Scope: TypeAlias = dict[str, Any]
Message: TypeAlias = dict[str, Any]
Receive: TypeAlias = Callable[[], Awaitable[Message]]
Send: TypeAlias = Callable[[Message], Awaitable[None]]
ASGIApp: TypeAlias = Callable[[Scope, Receive, Send], Awaitable[None]]


class BoundedPairingRequestBodyMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int = 512,
        read_timeout_seconds: float = 5.0,
    ) -> None:
        if max_body_bytes < 1:
            raise ValueError("Pairing request body limit must be positive.")
        if read_timeout_seconds <= 0:
            raise ValueError("Pairing request timeout must be positive.")
        self._app = app
        self._max_body_bytes = max_body_bytes
        self._read_timeout_seconds = read_timeout_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/api/pair":
            await self._app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is not None and content_length > self._max_body_bytes:
            await self._send_rejection(send, 413, "配對請求過大。")
            return

        body = bytearray()
        deadline = asyncio.get_running_loop().time() + self._read_timeout_seconds
        while True:
            remaining_seconds = deadline - asyncio.get_running_loop().time()
            if remaining_seconds <= 0:
                await self._send_rejection(send, 408, "配對請求逾時。")
                return
            try:
                async with asyncio.timeout(remaining_seconds):
                    message = await receive()
            except TimeoutError:
                await self._send_rejection(send, 408, "配對請求逾時。")
                return
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") != "http.request":
                continue
            chunk = message.get("body", b"")
            if not isinstance(chunk, bytes) or len(body) + len(chunk) > self._max_body_bytes:
                await self._send_rejection(send, 413, "配對請求過大。")
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        sent_body = False

        async def replay_receive() -> Message:
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self._app(scope, replay_receive, send)

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                length = int(value)
            except ValueError:
                return None
            return length if length >= 0 else None
        return None

    @staticmethod
    async def _send_rejection(send: Send, status_code: int, detail: str) -> None:
        body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
