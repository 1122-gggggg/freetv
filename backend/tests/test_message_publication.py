from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

from app import main
from app.commands.bus import CommandOutcome
from app.main import _dispatch_and_broadcast
from app.protocol import Command, CommandMessage, StateMessage
from app.state import ControllerState, LauncherTile


@dataclass
class BlockingAcknowledgementSocket:
    request_id_to_block: str | None = None
    acknowledgement_started: asyncio.Event = field(default_factory=asyncio.Event)
    release_acknowledgement: asyncio.Event = field(default_factory=asyncio.Event)
    sent: list[dict[str, object]] = field(default_factory=list)
    close_calls: int = 0
    url: object = field(default_factory=lambda: SimpleNamespace(path="/ws/remote"))

    async def send_json(self, payload: dict[str, object]) -> None:
        if payload.get("type") == "ack" and payload.get("request_id") == self.request_id_to_block:
            self.acknowledgement_started.set()
            await self.release_acknowledgement.wait()
        self.sent.append(payload)

    async def close(self) -> None:
        self.close_calls += 1


@dataclass
class FakeBus:
    outcomes: dict[Command, CommandOutcome]

    async def dispatch_command(self, command: Command) -> CommandOutcome:
        return self.outcomes[command]


@dataclass
class FakeConnections:
    states: list[StateMessage] = field(default_factory=list)
    active: bool = True
    removed: list[object] = field(default_factory=list)
    closed: list[object] = field(default_factory=list)

    async def is_active(self, _: object) -> bool:
        return self.active

    async def remove(self, websocket: object) -> None:
        self.removed.append(websocket)

    async def broadcast_state(self, state: StateMessage, **_: object) -> None:
        self.states.append(state)

    async def close_connections(self, connections: tuple[object, ...]) -> None:
        self.closed.extend(connections)
        for websocket in connections:
            await websocket.close()


def test_dispatch_publication_preserves_state_order_when_an_acknowledgement_stalls() -> None:
    async def scenario() -> None:
        first_state = ControllerState(focused_tile=LauncherTile.NETFLIX)
        second_state = ControllerState(focused_tile=LauncherTile.SETTINGS)
        app = SimpleNamespace(
            state=SimpleNamespace(
                runtime=SimpleNamespace(
                    bus=FakeBus(
                        {
                            Command.NAV_RIGHT: CommandOutcome(True, first_state),
                            Command.NAV_DOWN: CommandOutcome(True, second_state),
                        }
                    ),
                    pairing=SimpleNamespace(session_is_valid=lambda _: True),
                ),
                connections=FakeConnections(),
                dispatch_lock=asyncio.Lock(),
            )
        )
        first_socket = BlockingAcknowledgementSocket(request_id_to_block="first")
        second_socket = BlockingAcknowledgementSocket()
        first_message = CommandMessage(
            version=1, type="command", request_id="first", command=Command.NAV_RIGHT
        )
        second_message = CommandMessage(
            version=1, type="command", request_id="second", command=Command.NAV_DOWN
        )

        first = asyncio.create_task(_dispatch_and_broadcast(app, first_socket, first_message))
        await first_socket.acknowledgement_started.wait()
        second = asyncio.create_task(_dispatch_and_broadcast(app, second_socket, second_message))
        await asyncio.sleep(0)
        first_socket.release_acknowledgement.set()
        await asyncio.gather(first, second)

        assert [state.focused_tile for state in app.state.connections.states] == [
            LauncherTile.NETFLIX.value,
            LauncherTile.SETTINGS.value,
        ]

    asyncio.run(scenario())


def test_stalled_acknowledgement_is_bounded_and_does_not_block_later_dispatch(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        first_state = ControllerState(focused_tile=LauncherTile.NETFLIX)
        second_state = ControllerState(focused_tile=LauncherTile.SETTINGS)
        connections = FakeConnections()
        app = SimpleNamespace(
            state=SimpleNamespace(
                runtime=SimpleNamespace(
                    bus=FakeBus(
                        {
                            Command.NAV_RIGHT: CommandOutcome(True, first_state),
                            Command.NAV_DOWN: CommandOutcome(True, second_state),
                        }
                    ),
                    pairing=SimpleNamespace(session_is_valid=lambda _: True),
                ),
                connections=connections,
                dispatch_lock=asyncio.Lock(),
            )
        )
        stalled_socket = BlockingAcknowledgementSocket(request_id_to_block="stalled")
        responsive_socket = BlockingAcknowledgementSocket()
        stalled_message = CommandMessage(
            version=1, type="command", request_id="stalled", command=Command.NAV_RIGHT
        )
        responsive_message = CommandMessage(
            version=1, type="command", request_id="responsive", command=Command.NAV_DOWN
        )

        monkeypatch.setattr(main, "ACKNOWLEDGEMENT_SEND_TIMEOUT_SECONDS", 0.01)
        stalled = asyncio.create_task(_dispatch_and_broadcast(app, stalled_socket, stalled_message))
        await stalled_socket.acknowledgement_started.wait()
        responsive = asyncio.create_task(
            _dispatch_and_broadcast(app, responsive_socket, responsive_message)
        )

        results = await asyncio.wait_for(asyncio.gather(stalled, responsive), timeout=0.5)

        assert connections.removed == [stalled_socket]
        assert connections.closed == [stalled_socket]
        assert stalled_socket.close_calls == 1
        assert results == [False, True]
        assert [state.focused_tile for state in connections.states] == [
            LauncherTile.NETFLIX.value,
            LauncherTile.SETTINGS.value,
        ]
        assert [payload["request_id"] for payload in responsive_socket.sent] == ["responsive"]

    asyncio.run(scenario())


def test_removed_remote_session_cannot_dispatch() -> None:
    async def scenario() -> None:
        state = ControllerState(focused_tile=LauncherTile.NETFLIX)
        connections = FakeConnections(active=False)
        app = SimpleNamespace(
            state=SimpleNamespace(
                runtime=SimpleNamespace(
                    bus=FakeBus({Command.NAV_RIGHT: CommandOutcome(True, state)}),
                    pairing=SimpleNamespace(session_is_valid=lambda _: True),
                ),
                connections=connections,
                dispatch_lock=asyncio.Lock(),
            )
        )
        socket = BlockingAcknowledgementSocket()
        message = CommandMessage(
            version=1, type="command", request_id="revoked", command=Command.NAV_RIGHT
        )

        dispatched = await _dispatch_and_broadcast(app, socket, message, session=object())

        assert not dispatched
        assert connections.states == []

    asyncio.run(scenario())
