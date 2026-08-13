from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app import main
from app.commands.bus import CommandBus
from app.config import Settings
from app.controller import ControllerRuntime
from app.main import RemoteAuthenticationGuard, create_app
from app.protocol import Command, PointerActionMessage
from app.security.pairing import PairingService
from app.security.tokens import TokenStore
from app.state import ActiveApp, ControllerState, StateStore

TRUSTED_REMOTE_HEADERS = {"host": "127.0.0.1:8765", "origin": "https://127.0.0.1:8765"}
REMOTE_SOCKET_URL = "wss://127.0.0.1:8765/ws/remote"


def secure_remote_client(app) -> TestClient:
    return TestClient(app, base_url="https://127.0.0.1:8765", client=("127.0.0.1", 50_000))


@dataclass
class FakeApplications:
    async def open(self, app: ActiveApp) -> None:
        return None

    async def return_home(self) -> None:
        return None

    async def forward_command(self, command: Command) -> None:
        return None

    async def shutdown(self) -> None:
        return None


@dataclass
class FakePlayer:
    async def open(self) -> tuple[int, str]:
        return 1, "Demo Channel"

    async def close(self) -> None:
        return None

    async def toggle_pause(self) -> None:
        return None

    async def next(self) -> None:
        return None

    async def previous(self) -> None:
        return None

    async def change_channel(self, direction: int) -> tuple[int, str]:
        return 1, "Demo Channel"


@dataclass
class FakeVolume:
    async def increase(self) -> tuple[int, bool]:
        return 55, False

    async def decrease(self) -> tuple[int, bool]:
        return 45, False

    async def toggle_mute(self) -> tuple[int, bool]:
        return 50, True


@dataclass
class FakeInput:
    pointers: list[PointerActionMessage] = field(default_factory=list)

    async def pointer(self, message: PointerActionMessage) -> None:
        self.pointers.append(message)

    async def text(self, text: str) -> None:
        return None


@dataclass
class FakePower:
    async def sleep(self) -> None:
        return None


def make_app(tmp_path):
    token_store = TokenStore(tmp_path / "remotes.json")
    pairing = PairingService(token_store, code_factory=lambda: "482731")
    pairing.rotate_code()
    applications = FakeApplications()
    player = FakePlayer()
    bus = CommandBus(
        StateStore(ControllerState()),
        applications=applications,
        player=player,
        volume=FakeVolume(),
        input_controller=FakeInput(),
        power=FakePower(),
    )
    runtime = ControllerRuntime(bus=bus, pairing=pairing, applications=applications, player=player)
    return create_app(settings=Settings(), capabilities={}, runtime=runtime)


def authenticate(socket, token: str, request_id: str) -> None:
    socket.send_json(
        {"version": 1, "type": "authenticate", "request_id": request_id, "token": token}
    )
    assert socket.receive_json() == {
        "version": 1,
        "type": "ack",
        "request_id": request_id,
        "success": True,
        "error_code": None,
        "message": None,
    }
    assert socket.receive_json()["type"] == "state"


def test_remote_socket_rejects_commands_before_token_authentication(tmp_path) -> None:
    app = make_app(tmp_path)

    with secure_remote_client(app) as client:
        with client.websocket_connect(REMOTE_SOCKET_URL, headers=TRUSTED_REMOTE_HEADERS) as socket:
            socket.send_json(
                {"version": 1, "type": "command", "request_id": "before-auth", "command": "NAV_UP"}
            )
            error = socket.receive_json()

    assert error == {
        "version": 1,
        "type": "error",
        "code": "authentication_required",
        "message": "Authenticate before sending remote controls.",
    }


def test_paired_remote_receives_acknowledgement_and_state_after_command(tmp_path) -> None:
    app = make_app(tmp_path)
    runtime = app.state.runtime
    token = runtime.pairing.pair("482731")

    with secure_remote_client(app) as client:
        with client.websocket_connect(REMOTE_SOCKET_URL, headers=TRUSTED_REMOTE_HEADERS) as socket:
            authenticate(socket, token, "auth-1")
            socket.send_json(
                {"version": 1, "type": "command", "request_id": "nav-1", "command": "NAV_RIGHT"}
            )

            acknowledgement = socket.receive_json()
            state = socket.receive_json()

    assert acknowledgement["type"] == "ack"
    assert acknowledgement["request_id"] == "nav-1"
    assert acknowledgement["success"] is True
    assert state["type"] == "state"
    assert state["focused_tile"] == "netflix"


def test_all_paired_remotes_receive_state_broadcasts(tmp_path) -> None:
    app = make_app(tmp_path)
    runtime = app.state.runtime
    token_one = runtime.pairing.pair("482731")
    runtime.pairing.rotate_code()
    token_two = runtime.pairing.pair("482731")

    with secure_remote_client(app) as client:
        with (
            client.websocket_connect(REMOTE_SOCKET_URL, headers=TRUSTED_REMOTE_HEADERS) as first,
            client.websocket_connect(REMOTE_SOCKET_URL, headers=TRUSTED_REMOTE_HEADERS) as second,
        ):
            authenticate(first, token_one, "auth-1")
            authenticate(second, token_two, "auth-2")
            first.send_json(
                {"version": 1, "type": "command", "request_id": "nav-1", "command": "NAV_DOWN"}
            )

            assert first.receive_json()["type"] == "ack"
            first_state = first.receive_json()
            second_state = second.receive_json()

    assert first_state["focused_tile"] == "live_tv"
    assert second_state["focused_tile"] == "live_tv"


def test_invalid_remote_command_is_rejected_after_successful_authentication(tmp_path) -> None:
    app = make_app(tmp_path)
    token = app.state.runtime.pairing.pair("482731")

    with secure_remote_client(app) as client:
        with client.websocket_connect(REMOTE_SOCKET_URL, headers=TRUSTED_REMOTE_HEADERS) as socket:
            authenticate(socket, token, "auth-1")
            socket.send_json(
                {"version": 1, "type": "command", "request_id": "bad-1", "command": "RUN_SHELL"}
            )
            error = socket.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "invalid_message"


def test_tv_socket_rejects_cross_origin_commands(tmp_path) -> None:
    app = make_app(tmp_path)

    with TestClient(app, client=("127.0.0.1", 50_000)) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/ws/tv", headers={"origin": "https://attacker.example"}):
                pass

    assert error.value.code == 1008


def test_remote_socket_rejects_an_untrusted_origin(tmp_path) -> None:
    app = make_app(tmp_path)

    with secure_remote_client(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(
                REMOTE_SOCKET_URL,
                headers={**TRUSTED_REMOTE_HEADERS, "origin": "https://attacker.example:8765"},
            ):
                pass

    assert error.value.code == 1008


def test_remote_socket_rejects_an_untrusted_host_even_when_origin_matches(tmp_path) -> None:
    app = make_app(tmp_path)

    with secure_remote_client(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(
                REMOTE_SOCKET_URL,
                headers={
                    "host": "attacker.example:8765",
                    "origin": "https://attacker.example:8765",
                },
            ):
                pass

    assert error.value.code == 1008


def test_remote_socket_rejects_a_missing_browser_origin(tmp_path) -> None:
    app = make_app(tmp_path)

    with secure_remote_client(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(REMOTE_SOCKET_URL, headers={"host": "127.0.0.1:8765"}):
                pass

    assert error.value.code == 1008


def test_remote_socket_rejects_plain_websocket_from_the_lan(tmp_path, monkeypatch) -> None:
    app = make_app(tmp_path)
    lan_ip = "192.0.2.44"
    monkeypatch.setattr(
        main.psutil,
        "net_if_addrs",
        lambda: {"Wi-Fi": [SimpleNamespace(family=main.socket.AF_INET, address=lan_ip)]},
    )
    headers = {"host": f"{lan_ip}:8765", "origin": f"http://{lan_ip}:8765"}

    with TestClient(app, client=("192.0.2.87", 50_000)) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/ws/remote", headers=headers):
                pass

    assert error.value.code == 1008


def test_remote_socket_rejects_connections_when_pre_auth_capacity_is_exhausted(tmp_path) -> None:
    app = make_app(tmp_path)
    app.state.remote_authentication_guard = RemoteAuthenticationGuard(
        max_connections=0,
        max_connections_per_client=0,
    )

    with secure_remote_client(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(REMOTE_SOCKET_URL, headers=TRUSTED_REMOTE_HEADERS):
                pass

    assert error.value.code == 1008


def test_remote_socket_closes_an_idle_pre_authentication_connection(tmp_path, monkeypatch) -> None:
    app = make_app(tmp_path)
    monkeypatch.setattr(main, "REMOTE_AUTHENTICATION_TIMEOUT_SECONDS", 0.01)

    with secure_remote_client(app) as client:
        with client.websocket_connect(REMOTE_SOCKET_URL, headers=TRUSTED_REMOTE_HEADERS) as socket:
            with pytest.raises(WebSocketDisconnect) as error:
                socket.receive_json()

    assert error.value.code == 1008


def test_tv_socket_accepts_the_local_launcher_origin(tmp_path) -> None:
    app = make_app(tmp_path)

    with TestClient(app, client=("127.0.0.1", 50_000)) as client:
        with client.websocket_connect(
            "/ws/tv", headers={"origin": "http://127.0.0.1:8765"}
        ) as socket:
            assert socket.receive_json()["type"] == "state"


def test_loopback_pairing_endpoint_issues_one_token_per_code(tmp_path) -> None:
    app = make_app(tmp_path)

    with secure_remote_client(app) as client:
        pairing = client.get("/api/pairing", headers={"host": "127.0.0.1:8765"})
        paired = client.post(
            "/api/pair", json={"code": pairing.json()["code"]}, headers=TRUSTED_REMOTE_HEADERS
        )
        reused = client.post("/api/pair", json={"code": "482731"}, headers=TRUSTED_REMOTE_HEADERS)

    assert pairing.status_code == 200
    assert pairing.json()["code"] == "482731"
    assert paired.status_code == 200
    assert app.state.runtime.pairing.verify_token(paired.json()["token"])
    assert reused.status_code == 400


def test_pairing_code_endpoint_rejects_an_untrusted_host_from_loopback(tmp_path) -> None:
    app = make_app(tmp_path)

    with TestClient(app, client=("127.0.0.1", 50_000)) as client:
        response = client.get("/api/pairing", headers={"host": "attacker.example:8765"})

    assert response.status_code == 403


def test_pairing_endpoint_rejects_an_oversized_body_before_validation(tmp_path) -> None:
    app = make_app(tmp_path)

    with secure_remote_client(app) as client:
        response = client.post(
            "/api/pair",
            content=b"{" + (b"x" * 1024),
            headers={**TRUSTED_REMOTE_HEADERS, "content-type": "application/json"},
        )

    assert response.status_code == 413


def test_pairing_endpoint_rejects_plain_http_from_the_lan(tmp_path, monkeypatch) -> None:
    app = make_app(tmp_path)
    lan_ip = "192.0.2.44"
    monkeypatch.setattr(
        main.psutil,
        "net_if_addrs",
        lambda: {"Wi-Fi": [SimpleNamespace(family=main.socket.AF_INET, address=lan_ip)]},
    )
    headers = {"host": f"{lan_ip}:8765", "origin": f"http://{lan_ip}:8765"}

    with TestClient(app, client=("192.0.2.87", 50_000)) as client:
        response = client.post("/api/pair", json={"code": "482731"}, headers=headers)

    assert response.status_code == 403


def test_pairing_accepts_the_controller_lan_ip_origin(tmp_path, monkeypatch) -> None:
    app = make_app(tmp_path)
    lan_ip = "192.0.2.44"
    monkeypatch.setattr(
        main.psutil,
        "net_if_addrs",
        lambda: {"Wi-Fi": [SimpleNamespace(family=main.socket.AF_INET, address=lan_ip)]},
    )
    headers = {"host": f"{lan_ip}:8765", "origin": f"https://{lan_ip}:8765"}

    with TestClient(
        app, base_url=f"https://{lan_ip}:8765", client=("192.0.2.87", 50_000)
    ) as client:
        response = client.post("/api/pair", json={"code": "482731"}, headers=headers)

    assert response.status_code == 200
    assert app.state.runtime.pairing.verify_token(response.json()["token"])


def test_pairing_endpoint_rejects_non_ascii_digits_before_pairing(tmp_path) -> None:
    app = make_app(tmp_path)

    with TestClient(app, client=("127.0.0.1", 50_000)) as client:
        response = client.post("/api/pair", json={"code": "１２３４５６"})

    assert response.status_code == 422


def test_pairing_endpoint_rejects_an_untrusted_origin(tmp_path) -> None:
    app = make_app(tmp_path)

    with secure_remote_client(app) as client:
        response = client.post(
            "/api/pair",
            json={"code": "482731"},
            headers={**TRUSTED_REMOTE_HEADERS, "origin": "https://attacker.example:8765"},
        )

    assert response.status_code == 403


def test_pairing_endpoint_rejects_an_untrusted_host_even_when_origin_matches(tmp_path) -> None:
    app = make_app(tmp_path)

    with secure_remote_client(app) as client:
        response = client.post(
            "/api/pair",
            json={"code": "482731"},
            headers={"host": "attacker.example:8765", "origin": "https://attacker.example:8765"},
        )

    assert response.status_code == 403


def test_pairing_endpoint_requires_a_browser_origin(tmp_path) -> None:
    app = make_app(tmp_path)

    with secure_remote_client(app) as client:
        response = client.post(
            "/api/pair", json={"code": "482731"}, headers={"host": "127.0.0.1:8765"}
        )

    assert response.status_code == 403


def test_pairing_code_endpoint_is_not_exposed_to_lan_clients(tmp_path) -> None:
    app = make_app(tmp_path)

    with TestClient(app, client=("192.168.1.20", 50_000)) as client:
        response = client.get("/api/pairing")

    assert response.status_code == 403


def test_authenticated_remote_can_revoke_its_persisted_token(tmp_path) -> None:
    app = make_app(tmp_path)
    token = app.state.runtime.pairing.pair("482731")

    with secure_remote_client(app) as client:
        response = client.delete(
            "/api/remote-token",
            headers={**TRUSTED_REMOTE_HEADERS, "authorization": f"Bearer {token}"},
        )

    assert response.status_code == 204
    assert not app.state.runtime.pairing.verify_token(token)


def test_remote_token_revocation_rejects_an_untrusted_origin(tmp_path) -> None:
    app = make_app(tmp_path)
    token = app.state.runtime.pairing.pair("482731")

    with secure_remote_client(app) as client:
        response = client.delete(
            "/api/remote-token",
            headers={
                "host": "attacker.example:8765",
                "origin": "https://attacker.example:8765",
                "authorization": f"Bearer {token}",
            },
        )

    assert response.status_code == 403
    assert app.state.runtime.pairing.verify_token(token)


def test_remote_token_revocation_rejects_an_invalid_bearer_token(tmp_path) -> None:
    app = make_app(tmp_path)

    with secure_remote_client(app) as client:
        response = client.delete(
            "/api/remote-token",
            headers={
                **TRUSTED_REMOTE_HEADERS,
                "authorization": "Bearer invalid-token-value-that-is-long-enough",
            },
        )

    assert response.status_code == 401


def test_authenticated_remote_cannot_dispatch_after_its_token_is_revoked(tmp_path) -> None:
    app = make_app(tmp_path)
    token = app.state.runtime.pairing.pair("482731")

    with secure_remote_client(app) as client:
        with client.websocket_connect(REMOTE_SOCKET_URL, headers=TRUSTED_REMOTE_HEADERS) as socket:
            authenticate(socket, token, "auth-1")
            app.state.runtime.pairing.revoke_token(token)
            socket.send_json(
                {
                    "version": 1,
                    "type": "command",
                    "request_id": "after-revocation",
                    "command": "NAV_RIGHT",
                }
            )
            error = socket.receive_json()

    assert error == {
        "version": 1,
        "type": "error",
        "code": "authentication_failed",
        "message": "Remote token is invalid.",
    }
