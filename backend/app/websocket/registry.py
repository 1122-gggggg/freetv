from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable

from fastapi import WebSocket, WebSocketDisconnect

from app.protocol import StateMessage
from app.security.pairing import AuthenticatedRemoteSession

_STATE_SEND_TIMEOUT_SECONDS = 2.0


class ConnectionRegistry:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._sessions: dict[WebSocket, AuthenticatedRemoteSession] = {}
        self._lock = asyncio.Lock()

    async def add(
        self, websocket: WebSocket, *, session: AuthenticatedRemoteSession | None = None
    ) -> None:
        async with self._lock:
            self._connections.add(websocket)
            if session is not None:
                self._sessions[websocket] = session

    async def remove(self, websocket: WebSocket) -> None:
        await self._remove_connections((websocket,))

    async def is_active(self, websocket: WebSocket) -> bool:
        async with self._lock:
            return websocket in self._connections

    async def broadcast_state(
        self,
        state: StateMessage,
        *,
        session_is_valid: Callable[[AuthenticatedRemoteSession], bool] | None = None,
    ) -> None:
        payload = state.model_dump(mode="json")
        async with self._lock:
            connections = tuple(
                (websocket, self._sessions.get(websocket)) for websocket in self._connections
            )

        invalid_sessions = tuple(
            websocket
            for websocket, session in connections
            if session is not None
            and session_is_valid is not None
            and not session_is_valid(session)
        )
        if invalid_sessions:
            await self._remove_connections(invalid_sessions)
            await self.close_connections(invalid_sessions)

        async def send_state(
            websocket: WebSocket,
            session: AuthenticatedRemoteSession | None,
        ) -> WebSocket | None:
            if websocket in invalid_sessions:
                return None
            if (
                session is not None
                and session_is_valid is not None
                and not session_is_valid(session)
            ):
                return websocket
            try:
                async with asyncio.timeout(_STATE_SEND_TIMEOUT_SECONDS):
                    await websocket.send_json(payload)
            except (TimeoutError, OSError, RuntimeError, WebSocketDisconnect):
                return websocket
            return None

        results = await asyncio.gather(
            *(send_state(websocket, session) for websocket, session in connections)
        )
        failed = [websocket for websocket in results if websocket is not None]
        if failed:
            failed_connections = tuple(failed)
            await self._remove_connections(failed_connections)
            await self.close_connections(failed_connections)

    async def remove_invalid_sessions(
        self,
        session_is_valid: Callable[[AuthenticatedRemoteSession], bool],
    ) -> tuple[WebSocket, ...]:
        async with self._lock:
            connections = tuple(
                websocket
                for websocket, session in self._sessions.items()
                if not session_is_valid(session)
            )
            self._remove_connections_locked(connections)
            return connections

    async def remove_token_sessions(self, token: str) -> tuple[WebSocket, ...]:
        token_key = self._token_key(token)
        async with self._lock:
            connections = tuple(
                websocket
                for websocket, session in self._sessions.items()
                if session.token_key == token_key
            )
            self._remove_connections_locked(connections)
            return connections

    async def close_connections(self, connections: tuple[WebSocket, ...]) -> None:
        async def close_connection(websocket: WebSocket) -> None:
            try:
                async with asyncio.timeout(_STATE_SEND_TIMEOUT_SECONDS):
                    await websocket.close()
            except (TimeoutError, OSError, RuntimeError, WebSocketDisconnect):
                return

        await asyncio.gather(*(close_connection(websocket) for websocket in connections))

    async def close_token_sessions(self, token: str) -> None:
        await self.close_connections(await self.remove_token_sessions(token))

    async def close(self) -> None:
        async with self._lock:
            connections = tuple(self._connections)
            self._connections.clear()
            self._sessions.clear()
        await self.close_connections(connections)

    async def _remove_connections(self, connections: tuple[WebSocket, ...]) -> None:
        async with self._lock:
            self._remove_connections_locked(connections)

    def _remove_connections_locked(self, connections: tuple[WebSocket, ...]) -> None:
        for websocket in connections:
            self._connections.discard(websocket)
            self._sessions.pop(websocket, None)

    @staticmethod
    def _token_key(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()
