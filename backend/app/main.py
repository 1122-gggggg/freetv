from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from ipaddress import IPv4Address, IPv4Network, IPv6Address, ip_address
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
    SearchVideoMessage,
    TextInputMessage,
    parse_client_message,
)
from app.security.pairing import AuthenticatedRemoteSession, PairingCodeExpired, PairingCodeInvalid
from app.security.request_limits import BoundedPairingRequestBodyMiddleware
from app.state import ActiveApp
from app.system.network import eligible_lan_interface_names, is_eligible_lan_peer
from app.websocket.registry import ConnectionRegistry

logger = logging.getLogger(__name__)


REMOTE_AUTHENTICATION_TIMEOUT_SECONDS = 10.0
REMOTE_AUTHENTICATION_FAILED_CLOSE_CODE = 4401
ACKNOWLEDGEMENT_SEND_TIMEOUT_SECONDS = 2.0


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
    startup_runtime = getattr(app.state.runtime, "startup", None)
    if startup_runtime is not None:
        await startup_runtime()
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

    async def handle_application_exit(exited_app: ActiveApp) -> None:
        async with app.state.dispatch_lock:
            outcome = await app.state.runtime.bus.handle_application_exit(exited_app)
            if outcome.state_changed:
                await app.state.connections.broadcast_state(
                    outcome.state.to_wire(),
                    session_is_valid=app.state.runtime.pairing.session_is_valid,
                )

    set_exit_callback = getattr(
        resolved_runtime.applications,
        "set_application_exit_callback",
        None,
    )
    if set_exit_callback is not None:
        set_exit_callback(handle_application_exit)

    @app.get("/api/health")
    async def health() -> dict[str, bool | str]:
        return {
            "status": "ok",
            "backend": True,
            "frontend": resolved_frontend_available,
            "chrome_available": bool(app.state.capabilities.get("chrome_available", False)),
            "brave_available": bool(app.state.capabilities.get("brave_available", False)),
            "edge_available": bool(app.state.capabilities.get("edge_available", False)),
            "mpv_available": bool(app.state.capabilities.get("mpv_available", False)),
        }

    @app.get("/api/pairing")
    async def pairing_code(request: Request) -> dict[str, str | None]:
        _require_loopback_request(request)
        port = app.state.settings.server.port
        _require_local_tv_host(request, port)
        code, expires_at = app.state.runtime.pairing.current_code()
        return {
            "code": code,
            "expires_at": expires_at.isoformat(),
            "remote_url": _pairing_remote_url(port, app.state.settings.server.transport),
        }

    @app.post("/api/pair")
    async def pair_remote(request: Request, payload: PairRequest) -> dict[str, str]:
        _require_trusted_remote_origin(
            request, app.state.settings.server.port, app.state.settings.server.transport
        )
        client_host = _client_host(request)
        attempts: PairingAttemptGuard = app.state.pairing_attempts
        if not attempts.may_attempt(client_host):
            log_event(logger, "pair_failure", client=client_host, reason="rate_limited")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="配對嘗試次數過多。"
            )
        try:
            token = app.state.runtime.pairing.pair(payload.code)
        except PairingCodeExpired as error:
            attempts.record_failure(client_host)
            log_event(logger, "pair_failure", client=client_host, reason="expired_code")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="配對碼已過期。"
            ) from error
        except PairingCodeInvalid as error:
            attempts.record_failure(client_host)
            log_event(logger, "pair_failure", client=client_host, reason="invalid_code")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="配對碼無效。"
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
        _require_trusted_remote_origin(
            request, app.state.settings.server.port, app.state.settings.server.transport
        )
        token = _bearer_token(request)
        if token is None or not app.state.runtime.pairing.verify_token(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="遙控器權杖無效。"
            )
        connections: ConnectionRegistry = app.state.connections
        async with app.state.dispatch_lock:
            app.state.runtime.pairing.revoke_token(token)
            sessions = await connections.remove_token_sessions(token)
        await connections.close_connections(sessions)
        log_event(logger, "remote_token_revoked", client=_client_host(request))

    @app.websocket("/ws/remote")
    async def remote_socket(websocket: WebSocket) -> None:
        client_host = _websocket_host(websocket)
        expected_origin_scheme = _remote_websocket_origin_scheme(
            websocket, app.state.settings.server.transport
        )
        if (
            not _is_trusted_remote_access(client_host, websocket.headers.get("host"))
            or expected_origin_scheme is None
            or not _has_trusted_remote_origin(
                websocket.headers.get("origin"),
                websocket.headers.get("host"),
                app.state.settings.server.port,
                expected_scheme=expected_origin_scheme,
            )
        ):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
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
                    "請先驗證後再傳送遙控指令。",
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            except WebSocketDisconnect:
                return

            if not isinstance(first_message, AuthenticationMessage):
                await _send_error(
                    websocket,
                    "authentication_required",
                    "請先驗證後再傳送遙控指令。",
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            remote_session = app.state.runtime.pairing.authenticate_token(first_message.token)
            if remote_session is None or not app.state.runtime.pairing.session_is_valid(
                remote_session
            ):
                log_event(logger, "remote_auth_failure", client=client_host)
                await _send_error(websocket, "authentication_failed", "遙控器權杖無效。")
                await websocket.close(code=REMOTE_AUTHENTICATION_FAILED_CLOSE_CODE)
                return

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
                await _send_error(
                    websocket, "authentication_failed", "遙控器權杖已過期。"
                )
                await websocket.close(code=REMOTE_AUTHENTICATION_FAILED_CLOSE_CODE)
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
                        websocket, "invalid_message", "訊息不符合通訊協定第 1 版。"
                    )
                    continue
                if not isinstance(message, CommandMessage):
                    await _send_error(
                        websocket, "invalid_message", "電視端只接受指令。"
                    )
                    continue
                if not await _dispatch_and_broadcast(app, websocket, message):
                    return
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
                status_code=status.HTTP_404_NOT_FOUND, detail="尚未建置前端資源。"
            )
        return FileResponse(path)

    @app.get("/")
    @app.get("/tv")
    @app.get("/remote")
    async def frontend_route(request: Request) -> FileResponse:
        if request.url.path == "/remote":
            _require_trusted_remote_host(
                request, app.state.settings.server.port, app.state.settings.server.transport
            )
        index = frontend / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="尚未建置前端。",
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
            websocket, "invalid_message", "訊息不符合通訊協定第 1 版。"
        )
        return True

    if isinstance(message, AuthenticationMessage):
        await _send_error(
            websocket, "invalid_message", "僅能在連線時進行驗證。"
        )
        return True
    if await _dispatch_and_broadcast(app, websocket, message, session=session):
        return True
    if not await app.state.connections.is_active(websocket):
        return False
    log_event(logger, "remote_auth_failure", client=_websocket_host(websocket))
    await _send_error(websocket, "authentication_failed", "遙控器權杖無效。")
    await websocket.close(code=REMOTE_AUTHENTICATION_FAILED_CLOSE_CODE)
    return False


async def _dispatch_and_broadcast(
    app: FastAPI,
    websocket: WebSocket,
    message: CommandMessage | PointerActionMessage | TextInputMessage | SearchVideoMessage,
    *,
    session: AuthenticatedRemoteSession | None = None,
) -> bool:
    close_connection = False
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
        elif isinstance(message, SearchVideoMessage):
            outcome = await app.state.runtime.bus.dispatch_search(message)
            command_name = "search_video"
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
            async with asyncio.timeout(ACKNOWLEDGEMENT_SEND_TIMEOUT_SECONDS):
                await _send_acknowledgement(
                    websocket,
                    message.request_id,
                    success=outcome.success,
                    error_code=outcome.error_code,
                    message=outcome.message,
                )
        except (TimeoutError, OSError, RuntimeError, WebSocketDisconnect):
            await app.state.connections.remove(websocket)
            close_connection = True
        if outcome.state_changed:
            await app.state.connections.broadcast_state(
                outcome.state.to_wire(),
                session_is_valid=app.state.runtime.pairing.session_is_valid,
            )
    if close_connection:
        await app.state.connections.close_connections((websocket,))
        return False
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
            detail="這個端點僅供本機電視啟動器使用。",
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
            detail="這個端點僅供本機電視啟動器使用。",
        )


def _is_local_tv_host(host: str | None, port: int, *, default_port: int) -> bool:
    authority = _parse_authority(host, port, default_port=default_port)
    return authority is not None and authority[0] in {"127.0.0.1", "localhost", "::1"}


def _require_trusted_remote_peer(request: Request) -> None:
    if not _is_trusted_remote_access(_client_host(request), request.headers.get("host")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="遠端連線必須來自控制器區網。",
        )


def _require_trusted_remote_host(request: Request, port: int, transport: str) -> None:
    _require_trusted_remote_peer(request)
    expected_scheme = _remote_request_origin_scheme(request, transport)
    if expected_scheme is None or not _is_trusted_remote_host(
        request.headers.get("host"),
        port,
        default_port=_default_port_for_scheme(expected_scheme),
    ):
        detail = (
            "遠端連線必須使用此控制器區網 IP 的 HTTPS。"
            if transport == "https"
            else "遠端連線必須使用此控制器的區網 IP。"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


def _require_trusted_remote_origin(request: Request, port: int, transport: str) -> None:
    _require_trusted_remote_peer(request)
    expected_scheme = _remote_request_origin_scheme(request, transport)
    if expected_scheme is None or not _has_trusted_remote_origin(
        request.headers.get("origin"),
        request.headers.get("host"),
        port,
        expected_scheme=expected_scheme,
    ):
        detail = (
            "遠端連線必須使用此控制器區網 IP 的 HTTPS。"
            if transport == "https"
            else "遠端連線必須使用此控制器的區網 IP。"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


def _remote_request_origin_scheme(request: Request, transport: str) -> str | None:
    host = request.headers.get("host")
    if host is not None and _is_public_tunnel_host(host):
        return "https"
    if transport == "http":
        if request.url.scheme in {"http", "https"}:
            return request.url.scheme
        return None
    if request.url.scheme == "https":
        return "https"
    if request.url.scheme == "http" and _is_loopback(_client_host(request)):
        return "http"
    return None


def _remote_websocket_origin_scheme(websocket: WebSocket, transport: str) -> str | None:
    host = websocket.headers.get("host")
    if host is not None and _is_public_tunnel_host(host):
        return "https"
    scheme = websocket.scope.get("scheme")
    if transport == "http":
        if scheme == "ws":
            return "http"
        if scheme == "wss":
            return "https"
        return None
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
    if _is_public_tunnel_host(host):
        return host.casefold(), default_port if parsed_port is None else parsed_port
    effective_port = default_port if parsed_port is None else parsed_port
    if effective_port != port:
        return None
    return host.casefold(), effective_port


def _public_tunnel_origin() -> str | None:
    configured = os.environ.get("PC_TV_PUBLIC_ORIGIN", "").strip().lstrip("\ufeff")
    if not configured:
        origin_path = project_root() / "config" / "tunnel-origin.txt"
        if origin_path.is_file():
            configured = origin_path.read_text(encoding="utf-8-sig").strip()
    if not configured:
        return None
    parsed = urlsplit(configured)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        return None
    return f"https://{parsed.hostname.casefold()}"


def parse_cloudflared_origin(text: str) -> str | None:
    for token in text.split():
        parsed = urlsplit(token.strip("\"'"))
        host = parsed.hostname
        if (
            parsed.scheme.casefold() == "https"
            and host
            and host.endswith(".trycloudflare.com")
            and host.casefold() != "api.trycloudflare.com"
        ):
            return f"https://{host.casefold()}"
    return None


def _is_public_tunnel_host(host: str) -> bool:
    origin = _public_tunnel_origin()
    if origin is None:
        return False
    return urlsplit(origin).hostname == host.split(":", 1)[0].casefold()


def _pairing_remote_url(port: int, scheme: str) -> str | None:
    public_origin = _public_tunnel_origin()
    if public_origin is not None:
        return f"{public_origin}/remote"
    address = _default_route_ipv4_address() or _first_lan_ipv4_address()
    if address is None:
        return None
    return f"{scheme}://{address}:{port}/remote"


def _default_route_ipv4_address() -> IPv4Address | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = ip_address(probe.getsockname()[0])
    except OSError:
        return None
    if not isinstance(address, IPv4Address) or not _is_local_lan_ipv4_address(address):
        return None
    return address


def _first_lan_ipv4_address() -> IPv4Address | None:
    addresses = sorted(
        (
            address
            for address in _local_interface_addresses()
            if isinstance(address, IPv4Address) and _is_lan_ipv4_address(address)
        ),
        key=int,
    )
    return addresses[0] if addresses else None


RFC1918_NETWORKS: tuple[IPv4Network, ...] = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)


def _is_lan_ipv4_address(address: IPv4Address) -> bool:
    return any(address in network for network in RFC1918_NETWORKS)


def _is_local_lan_ipv4_address(address: IPv4Address) -> bool:
    return _is_lan_ipv4_address(address) and address in _local_interface_addresses()


def _is_trusted_remote_access(peer_host: str, request_host: str | None) -> bool:
    if request_host is not None and _is_public_tunnel_host(request_host):
        return True
    return _is_trusted_remote_peer(peer_host)


def _is_trusted_remote_peer(host: str) -> bool:
    if _is_loopback(host):
        return True
    try:
        address = ip_address(host.split("%", maxsplit=1)[0])
    except ValueError:
        return False
    if getattr(address, "ipv4_mapped", None):
        address = address.ipv4_mapped
        if address.is_loopback:
            return True
    if not isinstance(address, IPv4Address) or not _is_lan_ipv4_address(address):
        return False
    return is_eligible_lan_peer(address) and any(
        address in network for network in _local_lan_ipv4_networks()
    )


def _local_lan_ipv4_networks() -> list[IPv4Network]:
    networks: list[IPv4Network] = []
    eligible_names = eligible_lan_interface_names()
    if not eligible_names:
        return networks
    try:
        interfaces = psutil.net_if_addrs()
    except OSError:
        return networks
    for interface_name, interface_addresses in interfaces.items():
        if interface_name.casefold() not in eligible_names:
            continue
        for interface_address in interface_addresses:
            if getattr(interface_address, "family", None) != socket.AF_INET:
                continue
            raw_address = getattr(interface_address, "address", None)
            if not raw_address:
                continue
            try:
                address = ip_address(raw_address.split("%", maxsplit=1)[0])
            except ValueError:
                continue
            if not isinstance(address, IPv4Address) or not _is_lan_ipv4_address(address):
                continue
            raw_netmask = getattr(interface_address, "netmask", None)
            if raw_netmask:
                try:
                    network = IPv4Network(f"{address}/{raw_netmask}", strict=False)
                except ValueError:
                    network = IPv4Network(f"{address}/32", strict=False)
            else:
                network = IPv4Network(f"{address}/32", strict=False)
            networks.append(network)
    return networks


def _is_controller_host(host: str) -> bool:
    if host.casefold() == "localhost" or _is_public_tunnel_host(host):
        return True
    try:
        address = ip_address(host.split("%", maxsplit=1)[0])
    except ValueError:
        return False
    if address.is_loopback:
        return True
    if getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback:
        return True
    return isinstance(address, IPv4Address) and _is_local_lan_ipv4_address(address)


def _local_interface_addresses() -> set[IPv4Address | IPv6Address]:
    addresses: set[IPv4Address | IPv6Address] = {IPv4Address("127.0.0.1"), IPv6Address("::1")}
    eligible_names = eligible_lan_interface_names()
    if not eligible_names:
        return addresses
    try:
        interfaces = psutil.net_if_addrs()
    except OSError:
        return addresses
    for interface_name, interface_addresses in interfaces.items():
        if interface_name.casefold() not in eligible_names:
            continue
        for interface_address in interface_addresses:
            if getattr(interface_address, "family", None) != socket.AF_INET:
                continue
            raw_address = getattr(interface_address, "address", None)
            if not raw_address:
                continue
            try:
                address = ip_address(raw_address.split("%", maxsplit=1)[0])
            except ValueError:
                continue
            if isinstance(address, IPv4Address) and _is_lan_ipv4_address(address):
                addresses.add(address)
    return addresses


app = create_app()
