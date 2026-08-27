from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import WebSocketDisconnect

import app.websocket.registry as registry_module
from app.protocol import StateMessage
from app.security.pairing import AuthenticatedRemoteSession
from app.websocket.registry import ConnectionRegistry


@dataclass(eq=False)
class FakeSocket:
    fail_send: bool = False
    payloads: list[dict[str, object]] = field(default_factory=list)
    close_calls: int = 0

    async def send_json(self, payload: dict[str, object]) -> None:
        if self.fail_send:
            raise WebSocketDisconnect(code=1006)
        self.payloads.append(payload)

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(eq=False)
class NonReadingSocket(FakeSocket):
    async def send_json(self, payload: dict[str, object]) -> None:
        await asyncio.Event().wait()


@dataclass
class AsyncBarrier:
    target: int
    started: int = 0
    all_started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def wait(self) -> None:
        self.started += 1
        if self.started == self.target:
            self.all_started.set()
        await self.release.wait()


@dataclass(eq=False)
class BarrierSendSocket(FakeSocket):
    barrier: AsyncBarrier = field(default_factory=lambda: AsyncBarrier(1))

    async def send_json(self, payload: dict[str, object]) -> None:
        await self.barrier.wait()
        self.payloads.append(payload)


@dataclass(eq=False)
class BarrierCloseSocket(FakeSocket):
    barrier: AsyncBarrier = field(default_factory=lambda: AsyncBarrier(1))

    async def close(self) -> None:
        await self.barrier.wait()
        self.close_calls += 1


def remote_session(token: str, expires_at: datetime) -> AuthenticatedRemoteSession:
    return AuthenticatedRemoteSession(hashlib.sha256(token.encode("utf-8")).digest(), expires_at)


def test_state_broadcast_continues_when_a_peer_disconnects() -> None:
    async def scenario() -> None:
        registry = ConnectionRegistry()
        disconnected = FakeSocket(fail_send=True)
        healthy = FakeSocket()
        await registry.add(disconnected)  # type: ignore[arg-type]
        await registry.add(healthy)  # type: ignore[arg-type]

        await registry.broadcast_state(
            StateMessage(active_app="launcher", focused_tile="youtube", volume=50, muted=False)
        )

        assert healthy.payloads == [
            {
                "version": 1,
                "type": "state",
                "active_app": "launcher",
                "focused_tile": "youtube",
                "volume": 50,
                "muted": False,
                "channel_number": None,
                "channel_name": None,
                "status_message": None,
                "error_message": None,
                "netflix_context": None,
            }
        ]

    asyncio.run(scenario())


def test_state_broadcast_evicts_a_nonreading_remote_after_a_bounded_send_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        registry = ConnectionRegistry()
        nonreading = NonReadingSocket()
        healthy = FakeSocket()
        await registry.add(nonreading)  # type: ignore[arg-type]
        await registry.add(healthy)  # type: ignore[arg-type]

        await asyncio.wait_for(
            registry.broadcast_state(
                StateMessage(active_app="launcher", focused_tile="youtube", volume=50, muted=False)
            ),
            timeout=0.1,
        )

        assert nonreading.close_calls == 1
        assert not await registry.is_active(nonreading)  # type: ignore[arg-type]
        assert len(healthy.payloads) == 1

    monkeypatch.setattr(registry_module, "_STATE_SEND_TIMEOUT_SECONDS", 0.01, raising=False)
    asyncio.run(scenario())


def test_state_broadcast_sends_to_all_connections_concurrently() -> None:
    async def scenario() -> None:
        registry = ConnectionRegistry()
        barrier = AsyncBarrier(4)
        sockets = tuple(BarrierSendSocket(barrier=barrier) for _ in range(4))
        for socket in sockets:
            await registry.add(socket)  # type: ignore[arg-type]

        broadcast = asyncio.create_task(
            registry.broadcast_state(
                StateMessage(active_app="launcher", focused_tile="youtube", volume=50, muted=False)
            )
        )
        await asyncio.wait_for(barrier.all_started.wait(), timeout=0.5)
        barrier.release.set()
        await asyncio.wait_for(broadcast, timeout=0.5)

        assert all(len(socket.payloads) == 1 for socket in sockets)

    asyncio.run(scenario())


def test_connection_closes_run_concurrently() -> None:
    async def scenario() -> None:
        registry = ConnectionRegistry()
        barrier = AsyncBarrier(4)
        sockets = tuple(BarrierCloseSocket(barrier=barrier) for _ in range(4))

        closing = asyncio.create_task(
            registry.close_connections(sockets)  # type: ignore[arg-type]
        )
        await asyncio.wait_for(barrier.all_started.wait(), timeout=0.5)
        barrier.release.set()
        await asyncio.wait_for(closing, timeout=0.5)

        assert all(socket.close_calls == 1 for socket in sockets)

    asyncio.run(scenario())


def test_closing_a_revoked_token_session_preserves_other_paired_remotes() -> None:
    async def scenario() -> None:
        registry = ConnectionRegistry()
        revoked = FakeSocket()
        retained = FakeSocket()
        await registry.add(
            revoked,
            session=remote_session(
                "revoked-token-value-that-is-long-enough",
                datetime.now(UTC) + timedelta(days=1),
            ),
        )  # type: ignore[arg-type]
        await registry.add(
            retained,
            session=remote_session(
                "retained-token-value-that-is-long-enough",
                datetime.now(UTC) + timedelta(days=1),
            ),
        )  # type: ignore[arg-type]

        await registry.close_token_sessions("revoked-token-value-that-is-long-enough")
        await registry.broadcast_state(
            StateMessage(active_app="launcher", focused_tile="youtube", volume=50, muted=False)
        )

        assert revoked.close_calls == 1
        assert revoked.payloads == []
        assert retained.close_calls == 0
        assert len(retained.payloads) == 1

    asyncio.run(scenario())


def test_state_broadcast_closes_an_expired_remote_session_without_disclosing_state() -> None:
    async def scenario() -> None:
        registry = ConnectionRegistry()
        expired = FakeSocket()
        tv = FakeSocket()
        await registry.add(
            expired,
            session=remote_session(
                "expired-token-value-that-is-long-enough", datetime.now(UTC) - timedelta(seconds=1)
            ),
        )  # type: ignore[arg-type]
        await registry.add(tv)  # type: ignore[arg-type]

        await registry.broadcast_state(
            StateMessage(active_app="launcher", focused_tile="youtube", volume=50, muted=False),
            session_is_valid=lambda session: datetime.now(UTC) < session.expires_at,
        )

        assert expired.payloads == []
        assert expired.close_calls == 1
        assert not await registry.is_active(expired)  # type: ignore[arg-type]
        assert len(tv.payloads) == 1

    asyncio.run(scenario())


def test_removed_connection_is_no_longer_authorized_for_dispatch() -> None:
    async def scenario() -> None:
        registry = ConnectionRegistry()
        socket = FakeSocket()
        await registry.add(socket)  # type: ignore[arg-type]

        assert await registry.is_active(socket)  # type: ignore[arg-type]
        await registry.remove(socket)  # type: ignore[arg-type]
        assert not await registry.is_active(socket)  # type: ignore[arg-type]

    asyncio.run(scenario())
