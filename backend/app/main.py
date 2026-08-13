from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import psutil
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings, detect_capabilities, load_settings, project_root
from app.controller import ControllerRuntime, build_runtime
from app.logging import configure_logging, log_event
from app.protocol import (
    AcknowledgementMessage,
    AuthenticationMessage,
    CommandMessage,
    ErrorMessage,
    PointerActionMessage,
    TextInputMessage,
    parse_client_message,
)
from app.security.pairing import AuthenticatedRemoteSession, PairingCodeExpired, PairingCodeInvalid
from app.security.request_limits import BoundedPairingRequestBodyMiddleware
from app.websocket.registry import ConnectionRegistry

logger = logging.getLogger(__name__)


REMOTE_AUTHENTICATION_TIMEOUT_SECONDS = 10.0

HTML_SECURITY_HEADERS = {
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
}


class RemoteAuthenticationGuard:
    def __init__(self, *, max_connections: int = 16, max_connections_per_client: int = 4) -> None:
        if max_connections < 0 or max_connections_per_client < 0:
            raise ValueError("Remote authentication connection limits cannot be negative.")
        self._max_connections = max_connections
        self._max_connections_per_client = max_connections_per_client
        self._connections = 0
        self._connections_by_client: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, client_host: str) -> bool:
        async with self._lock:
            client_connections = self._connections_by_client.get(client_host, 0)
            if (
                self._connections >= self._max_connections
                or client_connections >= self._max_connections_per_client
            ):
                return False
            self._connections += 1
            self._connections_by_client[client_host] = client_connections + 1
            return True

    async def release(self, client_host: str) -> None:
        async with self._lock:
            client_connections = self._connections_by_client.get(client_host, 0)
            if client_connections <= 1:
                self._connections_by_client.pop(client_host, None)
            else:
                self._connections_by_client[client_host] = client_connections - 1
            if self._connections > 0:
                self._connections -= 1


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[0-9]{6}$")


class PairingAttemptGuard:
    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: float = 60,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, tuple[int, float]] = {}

    def may_attempt(self, client_host: str) -> bool:
        failures = self._failures.get(client_host)
        if failures is None:
            return True
        count, expires_at = failures
        if self._clock() >= expires_at:
            self._failures.pop(client_host, None)
            return True
        return count < self._max_attempts

    def record_failure(self, client_host: str) -> None:
        now = self._clock()
        failures = self._failures.get(client_host)
        if failures is None or now >= failures[1]:
            self._failures[client_host] = (1, now + self._window_seconds)
            return
        count = failures[0] + 1
        expires_at = now + self._window_seconds if count >= self._max_attempts else failures[1]
        self._failures[client_host] = (count, expires_at)

    def record_success(self, client_host: str) -> None:
        self._failures.pop(client_host, None)


@asynccontextmanager
async def controller_lifespan(app: FastAPI):
    configure_logging()
    log_event(logger, "controller_started")
    try:
        yield
    finally:
        await app.state.connections.close()
        await app.state.runtime.shutdown()
        log_event(logger, "controller_stopped")


def create_app(
    *,
    settings: Settings | None = None,
    capabilities: Mapping[str, bool] | None = None,
    runtime: ControllerRuntime | None = None,
    frontend_available: bool | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    resolved_runtime = runtime or build_runtime(resolved_settings)
    resolved_capabilities = dict(capabilities or detect_capabilities(resolved_settings))
    frontend = frontend_dist()
    resolved_frontend_available = (
        (frontend / "index.html").is_file() if frontend_available is None else frontend_available
    )

    app = FastAPI(title="PC TV Controller", version="0.1.0", lifespan=controller_lifespan)
    app.add_middleware(BoundedPairingRequestBodyMiddleware)
    app.state.settings = resolved_settings
    app.state.capabilities = resolved_capabilities
    app.state.runtime = resolved_runtime
    app.state.connections = ConnectionRegistry()
    app.state.pairing_attempts = PairingAttemptGuard()
    app.state.remote_authentication_guard = RemoteAuthenticationGuard()
    app.state.dispatch_lock = asyncio.Lock()

    @app.get("/api/health")
    async def health() -> dict[str, bool | str]:
        return {
            "status": "ok",
            "backend": True,
            "frontend": resolved_frontend_available,
            "brave_available": bool(app.state.capabilities.get("brave_available", False)),
            "edge_available": bool(app.state.capabilities.get("edge_available", False)),
            "mpv_available": bool(app.state.capabilities.get("mpv_available", False)),
        }

    @app.get("/api/pairing")
    async def pairing_code(request: Request) -> dict[str, str]:
        _require_loopback_request(request)
        _require_local_tv_host(request, app.state.settings.server.port)
        code, expires_at = app.state.runtime.pairing.current_code()
        return {"code": code, "expires_at": expires_at.isoformat()}

    @app.post("/api/pair")
    async def pair_remote(request: Request, payload: PairRequest) -> dict[str, str]:
        _require_trusted_remote_origin(request, app.state.settings.server.port)
        client_host = _client_host(request)
        attempts: PairingAttemptGuard = app.state.pairing_attempts
        if not attempts.may_attempt(client_host):
            log_event(logger, "pair_failure", client=client_host, reason="rate_limited")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many pairing attempts."
            )
        try:
            token = app.state.runtime.pairing.pair(payload.code)
        except PairingCodeExpired as error:
            attempts.record_failure(client_host)
            log_event(logger, "pair_failure", client=client_host, reason="expired_code")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Pairing code expired."
            ) from error
        except PairingCodeInvalid as error:
            attempts.record_failure(client_host)
            log_event(logger, "pair_failure", client=client_host, reason="invalid_code")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Pairing code is invalid."
            ) from error
        stale_sessions = await app.state.connections.remove_invalid_sessions(
            app.state.runtime.pairing.session_is_valid
        )
        await app.state.connections.close_connections(stale_sessions)
        attempts.record_success(client_host)
        log_event(logger, "pair_success", client=client_host)
        return {"token": token}

    @app.delete("/api/remote-token", status_code=status.HTTP_204_NO_CONTENT)
    async def revoke_remote_token(request: Request) -> None:
        _require_trusted_remote_origin(request, app.state.settings.server.port)
        token = _bearer_token(request)
        if token is None or not app.state.runtime.pairing.verify_token(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Remote token is invalid."
            )
        connections: ConnectionRegistry = app.state.connections
        async with app.state.dispatch_lock:
            app.state.runtime.pairing.revoke_token(token)
            sessions = await connections.remove_token_sessions(token)
        await connections.close_connections(sessions)
        log_event(logger, "remote_token_revoked", client=_client_host(request))

    @app.websocket("/ws/remote")
    async def remote_socket(websocket: WebSocket) -> None:
        expected_origin_scheme = _remote_websocket_origin_scheme(websocket)
        if expected_origin_scheme is None or not _has_trusted_remote_origin(
            websocket.headers.get("origin"),
            websocket.headers.get("host"),
            app.state.settings.server.port,
            expected_scheme=expected_origin_scheme,
        ):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        client_host = _websocket_host(websocket)
        authentication_guard: RemoteAuthenticationGuard = app.state.remote_authentication_guard
        if not await authentication_guard.acquire(client_host):
            log_event(logger, "remote_auth_admission_rejected", client=client_host)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        admission_acquired = True
        try:
            await websocket.accept()
            try:
                async with asyncio.timeout(REMOTE_AUTHENTICATION_TIMEOUT_SECONDS):
                    first_message = parse_client_message(await websocket.receive_json())
            except TimeoutError:
                log_event(logger, "remote_auth_timeout", client=client_host)
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            except (ValidationError, ValueError, TypeError):
                await _send_error(
                    websocket,
                    "authentication_required",
                    "Authenticate before sending remote controls.",
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            except WebSocketDisconnect:
                return

            if not isinstance(first_message, AuthenticationMessage):
                await _send_error(
                    websocket,
                    "authentication_required",
                    "Authenticate before sending remote controls.",
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            remote_session = app.state.runtime.pairing.authenticate_token(first_message.token)
            if remote_session is None or not app.state.runtime.pairing.session_is_valid(
                remote_session
            ):
                log_event(logger, "remote_auth_failure", client=client_host)
                await _send_error(websocket, "authentication_failed", "Remote token is invalid.")
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            await authentication_guard.release(client_host)
            admission_acquired = False
            connections: ConnectionRegistry = app.state.connections
            await connections.add(websocket, session=remote_session)
            log_event(logger, "remote_connected", client=client_host)
            try:
                await _send_acknowledgement(websocket, first_message.request_id, success=True)
                await websocket.send_json(
                    (await app.state.runtime.bus.state_snapshot()).to_wire().model_dump(mode="json")
                )
                session_timeout = max(
                    (remote_session.expires_at - app.state.runtime.pairing.now()).total_seconds(),
                    0.0,
                )
                async with asyncio.timeout(session_timeout):
                    while await _handle_remote_message(app, websocket, remote_session):
                        pass
            except TimeoutError:
                log_event(logger, "remote_session_expired", client=client_host)
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            except WebSocketDisconnect:
                return
            finally:
                await connections.remove(websocket)
                log_event(logger, "remote_disconnected", client=client_host)
        finally:
            if admission_acquired:
                await authentication_guard.release(client_host)

    @app.websocket("/ws/tv")
    async def tv_socket(websocket: WebSocket) -> None:
        if not (
            _is_loopback(_websocket_host(websocket))
            and _is_local_tv_origin(websocket, app.state.settings.server.port)
        ):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        connections: ConnectionRegistry = app.state.connections
        await connections.add(websocket)
        await websocket.send_json(
            (await app.state.runtime.bus.state_snapshot()).to_wire().model_dump(mode="json")
        )
        try:
            while True:
                try:
                    message = parse_client_message(await websocket.receive_json())
                except (ValidationError, ValueError, TypeError):
                    await _send_error(
                        websocket, "invalid_message", "Message does not match protocol version 1."
                    )
                    continue
                if not isinstance(message, CommandMessage):
                    await _send_error(
                        websocket, "invalid_message", "TV input accepts commands only."
                    )
                    continue
                await _dispatch_and_broadcast(app, websocket, message)
        except WebSocketDisconnect:
            return
        finally:
            await connections.remove(websocket)

    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/manifest.webmanifest")
    @app.get("/service-worker.js")
    @app.get("/icon.svg")
    async def frontend_public_asset(request: Request) -> FileResponse:
        path = frontend / request.url.path.rsplit("/", maxsplit=1)[-1]
        if not path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Frontend asset was not built."
            )
        return FileResponse(path)

    @app.get("/")
    @app.get("/tv")
    @app.get("/remote")
    async def frontend_route(request: Request) -> FileResponse:
        if request.url.path == "/remote":
            _require_trusted_remote_host(request, app.state.settings.server.port)
        index = frontend / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Frontend has not been built.",
            )
        return FileResponse(index, headers=HTML_SECURITY_HEADERS)

    return app


async def _handle_remote_message(
    app: FastAPI, websocket: WebSocket, session: AuthenticatedRemoteSession
) -> bool:
    payload = await websocket.receive_json()
    try:
        message = parse_client_message(payload)
    except (ValidationError, ValueError, TypeError):
        await _send_error(
            websocket, "invalid_message", "Message does not match protocol version 1."
        )
        return True

    if isinstance(message, AuthenticationMessage):
        await _send_error(
            websocket, "invalid_message", "Authentication is only accepted when connecting."
        )
        return True
    if await _dispatch_and_broadcast(app, websocket, message, session=session):
        return True
    log_event(logger, "remote_auth_failure", client=_websocket_host(websocket))
    await _send_error(websocket, "authentication_failed", "Remote token is invalid.")
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    return False


async def _dispatch_and_broadcast(
    app: FastAPI,
    websocket: WebSocket,
    message: CommandMessage | PointerActionMessage | TextInputMessage,
    *,
    session: AuthenticatedRemoteSession | None = None,
) -> bool:
    async with app.state.dispatch_lock:
        if session is not None and (
            not app.state.runtime.pairing.session_is_valid(session)
            or not await app.state.connections.is_active(websocket)
        ):
            return False
        if isinstance(message, CommandMessage):
            outcome = await app.state.runtime.bus.dispatch_command(message.command)
            command_name = message.command.value
        elif isinstance(message, PointerActionMessage):
            outcome = await app.state.runtime.bus.dispatch_pointer(message)
            command_name = message.action.value
        else:
            outcome = await app.state.runtime.bus.dispatch_text(message)
            command_name = "text_input"

        log_event(
            logger,
            "command",
            source="remote" if websocket.url.path.endswith("remote") else "tv",
            command=command_name,
        )
        try:
            await _send_acknowledgement(
                websocket,
                message.request_id,
                success=outcome.success,
                error_code=outcome.error_code,
                message=outcome.message,
            )
        except (OSError, RuntimeError, WebSocketDisconnect):
            await app.state.connections.remove(websocket)
        if outcome.state_changed:
            await app.state.connections.broadcast_state(
                outcome.state.to_wire(),
                session_is_valid=app.state.runtime.pairing.session_is_valid,
            )
        return True


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not separator or not token or token.strip() != token:
        return None
    return token


async def _send_acknowledgement(
    websocket: WebSocket,
    request_id: str,
    *,
    success: bool,
    error_code: str | None = None,
    message: str | None = None,
) -> None:
    acknowledgement = AcknowledgementMessage(
        request_id=request_id,
        success=success,
        error_code=error_code,
        message=message,
    )
    await websocket.send_json(acknowledgement.model_dump(mode="json"))


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    await websocket.send_json(ErrorMessage(code=code, message=message).model_dump(mode="json"))


def frontend_dist() -> Path:
    return project_root() / "frontend" / "dist"


def _client_host(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _websocket_host(websocket: WebSocket) -> str:
    return websocket.client.host if websocket.client is not None else "unknown"


def _require_loopback_request(request: Request) -> None:
    if not _is_loopback(_client_host(request)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is available only to the local TV launcher.",
        )


def _is_loopback(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        parsed = ip_address(host)
    except ValueError:
        return False
    if parsed.is_loopback:
        return True
    return bool(getattr(parsed, "ipv4_mapped", None) and parsed.ipv4_mapped.is_loopback)


def _is_local_tv_origin(websocket: WebSocket, port: int) -> bool:
    origin = websocket.headers.get("origin")
    return origin in {
        f"{scheme}://{host}:{port}"
        for scheme in ("http", "https")
        for host in ("127.0.0.1", "localhost", "[::1]")
    }


def _require_local_tv_host(request: Request, port: int) -> None:
    default_port = 443 if request.url.scheme == "https" else 80
    if not _is_local_tv_host(request.headers.get("host"), port, default_port=default_port):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is available only to the local TV launcher.",
        )


def _is_local_tv_host(host: str | None, port: int, *, default_port: int) -> bool:
    authority = _parse_authority(host, port, default_port=default_port)
    return authority is not None and authority[0] in {"127.0.0.1", "localhost", "::1"}


def _require_trusted_remote_host(request: Request, port: int) -> None:
    expected_scheme = _remote_request_origin_scheme(request)
    if expected_scheme is None or not _is_trusted_remote_host(
        request.headers.get("host"),
        port,
        default_port=_default_port_for_scheme(expected_scheme),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Remote access requires HTTPS at this controller's LAN IP.",
        )


def _require_trusted_remote_origin(request: Request, port: int) -> None:
    expected_scheme = _remote_request_origin_scheme(request)
    if expected_scheme is None or not _has_trusted_remote_origin(
        request.headers.get("origin"),
        request.headers.get("host"),
        port,
        expected_scheme=expected_scheme,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint must be called from this controller's HTTPS Remote page.",
        )


def _remote_request_origin_scheme(request: Request) -> str | None:
    if request.url.scheme == "https":
        return "https"
    if request.url.scheme == "http" and _is_loopback(_client_host(request)):
        return "http"
    return None


def _remote_websocket_origin_scheme(websocket: WebSocket) -> str | None:
    scheme = websocket.scope.get("scheme")
    if scheme == "wss":
        return "https"
    if scheme == "ws" and _is_loopback(_websocket_host(websocket)):
        return "http"
    return None


def _is_trusted_remote_host(host: str | None, port: int, *, default_port: int) -> bool:
    authority = _parse_authority(host, port, default_port=default_port)
    return authority is not None and _is_controller_host(authority[0])


def _has_trusted_remote_origin(
    origin: str | None,
    host: str | None,
    port: int,
    *,
    expected_scheme: str,
) -> bool:
    default_port = _default_port_for_scheme(expected_scheme)
    origin_authority = _parse_origin(origin, port, expected_scheme=expected_scheme)
    host_authority = _parse_authority(host, port, default_port=default_port)
    return (
        origin_authority is not None
        and host_authority is not None
        and origin_authority == host_authority
        and _is_controller_host(origin_authority[0])
    )


def _parse_origin(
    origin: str | None,
    port: int,
    *,
    expected_scheme: str,
) -> tuple[str, int] | None:
    if origin is None or not origin or origin.strip() != origin:
        return None
    try:
        parsed = urlsplit(origin)
        parsed_port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != expected_scheme
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return _normalized_authority(
        parsed.hostname,
        parsed_port,
        port,
        default_port=_default_port_for_scheme(expected_scheme),
    )


def _parse_authority(
    authority: str | None,
    port: int,
    *,
    default_port: int,
) -> tuple[str, int] | None:
    if authority is None or not authority or authority.strip() != authority:
        return None
    try:
        parsed = urlsplit(f"//{authority}")
        parsed_port = parsed.port
    except ValueError:
        return None
    if (
        not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return _normalized_authority(parsed.hostname, parsed_port, port, default_port=default_port)


def _default_port_for_scheme(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _normalized_authority(
    host: str | None,
    parsed_port: int | None,
    port: int,
    *,
    default_port: int,
) -> tuple[str, int] | None:
    if host is None:
        return None
    effective_port = default_port if parsed_port is None else parsed_port
    if effective_port != port:
        return None
    return host.casefold(), effective_port


def _is_controller_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ip_address(host.split("%", maxsplit=1)[0])
    except ValueError:
        return False
    if address.is_loopback:
        return True
    return address in _local_interface_addresses()


def _local_interface_addresses() -> set[IPv4Address | IPv6Address]:
    addresses: set[IPv4Address | IPv6Address] = set()
    try:
        interfaces = psutil.net_if_addrs().values()
    except OSError:
        return addresses
    for interface_addresses in interfaces:
        for interface_address in interface_addresses:
            if interface_address.family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            try:
                addresses.add(ip_address(interface_address.address.split("%", maxsplit=1)[0]))
            except ValueError:
                continue
    return addresses


app = create_app()
