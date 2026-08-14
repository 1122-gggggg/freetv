#!/usr/bin/env python3
"""Opt-in real-controller integration smoke client.

Tests an already running PC TV Controller instance (e.g. started with
`start.ps1 -NoBrowser`) over real HTTPS and authenticated WSS without launching
external applications (YouTube, Netflix, mpv) or sending text/pointer input.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import ssl
import sys
import uuid
from dataclasses import dataclass
from ipaddress import IPv4Address, ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import websockets

logger = logging.getLogger("integration_smoke")

PROTOCOL_VERSION = 1


class SmokeValidationError(Exception):
    """Raised when an input or protocol validation assertion fails."""


@dataclass(frozen=True, slots=True)
class SmokeConfig:
    port: int = 8765
    loopback_host: str = "127.0.0.1"
    lan_host: str | None = None
    ca_cert_path: Path | None = None
    timeout: float = 10.0


@dataclass(slots=True)
class SmokeResult:
    health_ok: bool = False
    pairing_code_retrieved: bool = False
    paired: bool = False
    tv_ws_connected: bool = False
    remote_ws_authenticated: bool = False
    nav_right_acknowledged: bool = False
    nav_right_state_observed: bool = False
    home_acknowledged: bool = False
    home_state_observed: bool = False
    token_revoked: bool = False

    @property
    def all_passed(self) -> bool:
        return (
            self.health_ok
            and self.pairing_code_retrieved
            and self.paired
            and self.tv_ws_connected
            and self.remote_ws_authenticated
            and self.nav_right_acknowledged
            and self.nav_right_state_observed
            and self.home_acknowledged
            and self.home_state_observed
            and self.token_revoked
        )


def validate_host_address(host: str) -> str:
    """Validate that host is a valid IPv4 address or loopback name."""
    if not host or not isinstance(host, str):
        raise SmokeValidationError("Host must be a non-empty string.")
    host_clean = host.strip()
    if host_clean.casefold() in {"localhost", "127.0.0.1", "::1"}:
        return host_clean
    try:
        addr = ip_address(host_clean)
        if isinstance(addr, IPv4Address):
            return str(addr)
        raise SmokeValidationError(f"Expected IPv4 address or loopback, got IPv6: {host}")
    except ValueError as err:
        raise SmokeValidationError(f"Invalid host address '{host}': {err}") from err


def validate_port(port: int | str) -> int:
    """Validate that port is an integer in the 1-65535 range."""
    try:
        val = int(port)
    except (ValueError, TypeError) as err:
        raise SmokeValidationError(f"Port must be an integer, got: {port}") from err
    if not 1 <= val <= 65535:
        raise SmokeValidationError(f"Port must be between 1 and 65535, got: {val}")
    return val


def parse_and_validate_remote_url(remote_url: str) -> tuple[str, int]:
    """Parse remote_url (e.g. https://192.168.1.50:8765/remote) and validate scheme, host, port."""
    if not remote_url or not isinstance(remote_url, str):
        raise SmokeValidationError("Remote URL must be a non-empty string.")
    try:
        parsed = urlsplit(remote_url)
    except Exception as err:
        raise SmokeValidationError(f"Could not parse remote URL '{remote_url}': {err}") from err

    if parsed.scheme.casefold() != "https":
        raise SmokeValidationError(f"Remote URL scheme must be 'https', got '{parsed.scheme}'.")
    if not parsed.hostname:
        raise SmokeValidationError(f"Remote URL missing hostname: '{remote_url}'.")

    host = validate_host_address(parsed.hostname)
    port = validate_port(parsed.port or 443)
    return host, port


def create_request_id(prefix: str = "smoke") -> str:
    """Generate a protocol-compliant request_id."""
    clean_prefix = prefix.replace("_", "-").strip("-") or "smoke"
    suffix = uuid.uuid4().hex[:12]
    return f"{clean_prefix}-{suffix}"


def build_auth_message(token: str, request_id: str | None = None) -> dict[str, Any]:
    """Construct an authentication wire message."""
    if not token or not isinstance(token, str) or len(token) < 32 or len(token) > 512:
        raise SmokeValidationError("Token must be a string between 32 and 512 characters.")
    req_id = request_id or create_request_id("auth")
    return {
        "version": PROTOCOL_VERSION,
        "type": "authenticate",
        "request_id": req_id,
        "token": token,
    }


def build_command_message(command: str, request_id: str | None = None) -> dict[str, Any]:
    """Construct a command wire message."""
    valid_commands = {
        "NAV_UP",
        "NAV_DOWN",
        "NAV_LEFT",
        "NAV_RIGHT",
        "OK",
        "BACK",
        "HOME",
        "PLAY_PAUSE",
        "NEXT",
        "PREVIOUS",
        "VOLUME_UP",
        "VOLUME_DOWN",
        "MUTE",
        "CHANNEL_UP",
        "CHANNEL_DOWN",
        "OPEN_YOUTUBE",
        "OPEN_NETFLIX",
        "OPEN_LIVE_TV",
        "OPEN_BROWSER",
        "POWER_SLEEP",
    }
    if command not in valid_commands:
        raise SmokeValidationError(f"Invalid command '{command}'. Must be one of {valid_commands}")
    req_id = request_id or create_request_id("cmd")
    return {
        "version": PROTOCOL_VERSION,
        "type": "command",
        "request_id": req_id,
        "command": command,
    }


def validate_acknowledgement(
    message: dict[str, Any],
    expected_request_id: str,
    *,
    expect_success: bool = True,
) -> None:
    """Verify an acknowledgement wire message matches expectations."""
    if not isinstance(message, dict):
        raise SmokeValidationError(f"Expected dict message, got {type(message).__name__}")
    if message.get("version") != PROTOCOL_VERSION:
        raise SmokeValidationError(
            f"Expected protocol version {PROTOCOL_VERSION}, got {message.get('version')}"
        )
    if message.get("type") != "ack":
        raise SmokeValidationError(f"Expected message type 'ack', got '{message.get('type')}'")
    if message.get("request_id") != expected_request_id:
        raise SmokeValidationError(
            f"Expected request_id '{expected_request_id}', got '{message.get('request_id')}'"
        )
    if message.get("success") is not expect_success:
        raise SmokeValidationError(
            f"Expected success={expect_success}, got success={message.get('success')}, "
            f"error_code={message.get('error_code')}, error_message={message.get('message')}"
        )


def validate_state(
    message: dict[str, Any],
    *,
    expected_active_app: str | None = None,
    expected_focused_tile: str | None = None,
) -> None:
    """Verify a state wire message structure and expected values."""
    if not isinstance(message, dict):
        raise SmokeValidationError(f"Expected dict message, got {type(message).__name__}")
    if message.get("version") != PROTOCOL_VERSION:
        raise SmokeValidationError(
            f"Expected protocol version {PROTOCOL_VERSION}, got {message.get('version')}"
        )
    if message.get("type") != "state":
        raise SmokeValidationError(f"Expected message type 'state', got '{message.get('type')}'")

    active_app = message.get("active_app")
    focused_tile = message.get("focused_tile")
    volume = message.get("volume")
    muted = message.get("muted")

    if not isinstance(active_app, str):
        raise SmokeValidationError(f"Invalid active_app in state: {active_app}")
    if not isinstance(focused_tile, str):
        raise SmokeValidationError(f"Invalid focused_tile in state: {focused_tile}")
    if not isinstance(volume, int) or not (0 <= volume <= 100):
        raise SmokeValidationError(f"Invalid volume in state: {volume}")
    if not isinstance(muted, bool):
        raise SmokeValidationError(f"Invalid muted in state: {muted}")

    if expected_active_app is not None and active_app != expected_active_app:
        raise SmokeValidationError(
            f"Expected active_app '{expected_active_app}', got '{active_app}'"
        )
    if expected_focused_tile is not None and focused_tile != expected_focused_tile:
        raise SmokeValidationError(
            f"Expected focused_tile '{expected_focused_tile}', got '{focused_tile}'"
        )


def build_ssl_context(ca_cert_path: Path) -> ssl.SSLContext:
    """Create an SSL context trusting the local controller CA certificate."""
    if not ca_cert_path.is_file():
        raise SmokeValidationError(f"CA certificate file does not exist: {ca_cert_path}")
    try:
        raw_bytes = ca_cert_path.read_bytes()
    except OSError as err:
        raise SmokeValidationError(
            f"Could not read CA certificate file '{ca_cert_path}': {err}"
        ) from err

    try:
        if b"-----BEGIN " in raw_bytes:
            ctx = ssl.create_default_context(cafile=str(ca_cert_path))
        else:
            pem_cert = ssl.DER_cert_to_PEM_cert(raw_bytes)
            ctx = ssl.create_default_context(cadata=pem_cert)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx
    except (ssl.SSLError, ValueError, TypeError, OSError) as err:
        raise SmokeValidationError(
            f"Failed to load CA certificate from '{ca_cert_path}': {err}"
        ) from err


def find_project_root() -> Path:
    """Find repository root directory."""
    current = Path(__file__).resolve().parent
    if (current / "start.ps1").is_file():
        return current.parent
    if (current.parent / "scripts" / "start.ps1").is_file():
        return current.parent
    return current


def find_default_ca_cert(root: Path) -> Path:
    """Return default path to local CA certificate."""
    return root / "config" / "tls" / "pc-tv-box-local-ca.cer"


async def connect_ws(
    uri: str,
    *,
    ssl_context: ssl.SSLContext,
    headers: dict[str, str],
    timeout: float = 10.0,
):
    """Establish a WebSocket connection with version-compatible header argument."""
    sig = inspect.signature(websockets.connect)
    kwargs: dict[str, Any] = {
        "ssl": ssl_context,
        "open_timeout": timeout,
        "close_timeout": timeout,
    }
    if "additional_headers" in sig.parameters:
        kwargs["additional_headers"] = headers
    else:
        kwargs["extra_headers"] = headers
    return await websockets.connect(uri, **kwargs)


async def receive_json_message(ws: Any, timeout: float = 10.0) -> dict[str, Any]:
    """Receive and parse a single JSON message from a WebSocket."""
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


async def run_smoke_test(config: SmokeConfig) -> SmokeResult:
    """Execute the end-to-end integration smoke workflow."""
    result = SmokeResult()
    root = find_project_root()
    ca_path = config.ca_cert_path or find_default_ca_cert(root)
    if not ca_path.is_file():
        raise SmokeValidationError(
            f"Local CA certificate was not found at '{ca_path}'. "
            "Ensure the controller is running or specify --ca-cert."
        )

    ssl_ctx = build_ssl_context(ca_path)
    port = validate_port(config.port)
    loopback_host = validate_host_address(config.loopback_host)
    loopback_origin = f"https://{loopback_host}:{port}"
    loopback_base_url = loopback_origin

    token: str | None = None
    lan_host: str | None = config.lan_host
    lan_origin: str = ""
    lan_base_url: str = ""

    async with httpx.AsyncClient(verify=ssl_ctx, timeout=config.timeout) as http_client:
        try:
            # 1. Health check
            logger.info("1/7: Checking GET /api/health...")
            health_resp = await http_client.get(
                f"{loopback_base_url}/api/health",
                headers={"Host": f"{loopback_host}:{port}"},
            )
            if health_resp.status_code != 200:
                raise SmokeValidationError(
                    f"Health check failed with status {health_resp.status_code}: {health_resp.text}"
                )
            health_data = health_resp.json()
            if health_data.get("status") != "ok" or not health_data.get("backend"):
                raise SmokeValidationError(f"Health payload invalid: {health_data}")
            result.health_ok = True
            logger.info("Health check OK: status=%s, backend=%s", health_data.get("status"), health_data.get("backend"))

            # 2. Get loopback pairing state
            logger.info("2/7: Getting pairing state from GET /api/pairing...")
            pairing_resp = await http_client.get(
                f"{loopback_base_url}/api/pairing",
                headers={"Host": f"{loopback_host}:{port}"},
            )
            if pairing_resp.status_code != 200:
                raise SmokeValidationError(
                    f"Pairing request failed with status {pairing_resp.status_code}: {pairing_resp.text}"
                )
            pairing_data = pairing_resp.json()
            code = pairing_data.get("code")
            if not code or not isinstance(code, str) or len(code) != 6 or not code.isdigit():
                raise SmokeValidationError(f"Invalid pairing code received: {code}")
            result.pairing_code_retrieved = True
            logger.info("Pairing code retrieved successfully.")

            # Resolve LAN host and port
            remote_url = pairing_data.get("remote_url")
            if lan_host is None:
                if remote_url:
                    parsed_lan_host, parsed_port = parse_and_validate_remote_url(remote_url)
                    lan_host = parsed_lan_host
                    port = parsed_port
                else:
                    lan_host = loopback_host
            else:
                lan_host = validate_host_address(lan_host)

            lan_origin = f"https://{lan_host}:{port}"
            lan_base_url = lan_origin
            logger.info("LAN Remote origin resolved to: %s", lan_origin)

            # 3. POST pairing code to numeric LAN HTTPS origin
            logger.info("3/7: Pairing remote via POST /api/pair with exact Origin...")
            pair_resp = await http_client.post(
                f"{lan_base_url}/api/pair",
                json={"code": code},
                headers={
                    "Host": f"{lan_host}:{port}",
                    "Origin": lan_origin,
                    "Content-Type": "application/json",
                },
            )
            if pair_resp.status_code != 200:
                raise SmokeValidationError(
                    f"Pairing POST failed with status {pair_resp.status_code}: {pair_resp.text}"
                )
            pair_data = pair_resp.json()
            token = pair_data.get("token")
            if not token or not isinstance(token, str) or len(token) < 32:
                raise SmokeValidationError("Pairing response did not contain a valid token.")
            result.paired = True
            logger.info("Remote paired successfully (token acquired, redacted).")

            # 4. Authenticate both Loopback TV WSS and LAN Remote WSS
            logger.info("4/7: Connecting TV WSS and authenticating LAN Remote WSS...")
            tv_ws_url = f"wss://{loopback_host}:{port}/ws/tv"
            tv_headers = {
                "Host": f"{loopback_host}:{port}",
                "Origin": loopback_origin,
            }
            remote_ws_url = f"wss://{lan_host}:{port}/ws/remote"
            remote_headers = {
                "Host": f"{lan_host}:{port}",
                "Origin": lan_origin,
            }

            tv_ws = await connect_ws(
                tv_ws_url, ssl_context=ssl_ctx, headers=tv_headers, timeout=config.timeout
            )
            remote_ws = await connect_ws(
                remote_ws_url, ssl_context=ssl_ctx, headers=remote_headers, timeout=config.timeout
            )

            try:
                # Receive TV initial state
                tv_init_state = await receive_json_message(tv_ws, timeout=config.timeout)
                validate_state(tv_init_state, expected_active_app="launcher")
                result.tv_ws_connected = True
                logger.info(
                    "TV WSS connected. Initial state: active_app=%s, focused_tile=%s",
                    tv_init_state.get("active_app"),
                    tv_init_state.get("focused_tile"),
                )

                # Send Remote Authentication
                auth_req_id = create_request_id("auth")
                auth_msg = build_auth_message(token, auth_req_id)
                await remote_ws.send(json.dumps(auth_msg))

                # Receive Remote Auth Ack
                remote_ack = await receive_json_message(remote_ws, timeout=config.timeout)
                validate_acknowledgement(remote_ack, auth_req_id, expect_success=True)

                # Receive Remote Initial State
                remote_init_state = await receive_json_message(remote_ws, timeout=config.timeout)
                validate_state(remote_init_state, expected_active_app="launcher")
                result.remote_ws_authenticated = True
                logger.info(
                    "Remote WSS authenticated. Initial state: active_app=%s, focused_tile=%s",
                    remote_init_state.get("active_app"),
                    remote_init_state.get("focused_tile"),
                )

                # 5. Send NAV_RIGHT through the Remote
                logger.info("5/7: Sending NAV_RIGHT through Remote...")
                nav_req_id = create_request_id("nav-right")
                nav_msg = build_command_message("NAV_RIGHT", nav_req_id)
                await remote_ws.send(json.dumps(nav_msg))

                # Remote receives Ack
                nav_ack = await receive_json_message(remote_ws, timeout=config.timeout)
                validate_acknowledgement(nav_ack, nav_req_id, expect_success=True)
                result.nav_right_acknowledged = True

                # Remote receives State
                remote_nav_state = await receive_json_message(remote_ws, timeout=config.timeout)
                validate_state(remote_nav_state, expected_active_app="launcher")

                # TV receives broadcasted State
                tv_nav_state = await receive_json_message(tv_ws, timeout=config.timeout)
                validate_state(tv_nav_state, expected_active_app="launcher")

                if remote_nav_state.get("focused_tile") != tv_nav_state.get("focused_tile"):
                    raise SmokeValidationError(
                        f"State mismatch after NAV_RIGHT: Remote focused_tile={remote_nav_state.get('focused_tile')} "
                        f"vs TV focused_tile={tv_nav_state.get('focused_tile')}"
                    )
                result.nav_right_state_observed = True
                logger.info(
                    "NAV_RIGHT verified. Remote and TV focus tile updated to: %s",
                    remote_nav_state.get("focused_tile"),
                )

                # 6. Send HOME through the Remote
                logger.info("6/7: Sending HOME through Remote...")
                home_req_id = create_request_id("home")
                home_msg = build_command_message("HOME", home_req_id)
                await remote_ws.send(json.dumps(home_msg))

                # Remote receives Ack
                home_ack = await receive_json_message(remote_ws, timeout=config.timeout)
                validate_acknowledgement(home_ack, home_req_id, expect_success=True)
                result.home_acknowledged = True

                # Remote receives State
                remote_home_state = await receive_json_message(remote_ws, timeout=config.timeout)
                validate_state(remote_home_state, expected_active_app="launcher")

                # TV receives broadcasted State
                tv_home_state = await receive_json_message(tv_ws, timeout=config.timeout)
                validate_state(tv_home_state, expected_active_app="launcher")

                result.home_state_observed = True
                logger.info(
                    "HOME verified. Remote and TV active app confirmed: %s",
                    remote_home_state.get("active_app"),
                )

            finally:
                await tv_ws.close()
                await remote_ws.close()

        finally:
            # 7. Revoke issued remote token in finally
            if token and lan_base_url:
                logger.info("7/7: Revoking issued remote token in finally...")
                try:
                    revoke_resp = await http_client.request(
                        "DELETE",
                        f"{lan_base_url}/api/remote-token",
                        headers={
                            "Host": f"{lan_host}:{port}",
                            "Origin": lan_origin,
                            "Authorization": f"Bearer {token}",
                        },
                    )
                    if revoke_resp.status_code in {200, 204}:
                        result.token_revoked = True
                        logger.info("Token revoked successfully.")
                    else:
                        logger.warning(
                            "Token revocation returned unexpected status: %s",
                            revoke_resp.status_code,
                        )
                except Exception as err:
                    logger.error("Failed to revoke token during cleanup: %s", err)

    return result


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Integration smoke client against an active PC TV Controller."
    )
    parser.add_argument(
        "--ca-cert",
        type=Path,
        default=None,
        help="Path to local CA certificate (defaults to config/tls/pc-tv-box-local-ca.cer).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Controller server port (default: 8765).",
    )
    parser.add_argument(
        "--loopback-host",
        type=str,
        default="127.0.0.1",
        help="Loopback host for TV launcher connection (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--lan-ip",
        type=str,
        default=None,
        help="Optional explicit LAN IP for remote connection (default: discovered from /api/pairing).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Timeout in seconds for operations (default: 10.0).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    config = SmokeConfig(
        port=args.port,
        loopback_host=args.loopback_host,
        lan_host=args.lan_ip,
        ca_cert_path=args.ca_cert,
        timeout=args.timeout,
    )
    try:
        result = asyncio.run(run_smoke_test(config))
        if not result.all_passed:
            logger.error("Integration smoke test finished with incomplete stages: %s", result)
            return 1
        print("\n========================================")
        print("Integration Smoke Test: ALL PASSED (OK)")
        print("========================================")
        print(f"Health check:            {'PASS' if result.health_ok else 'FAIL'}")
        print(f"Pairing code retrieved:  {'PASS' if result.pairing_code_retrieved else 'FAIL'}")
        print(f"Remote paired:           {'PASS' if result.paired else 'FAIL'}")
        print(f"TV WS connected:         {'PASS' if result.tv_ws_connected else 'FAIL'}")
        print(f"Remote WS authenticated: {'PASS' if result.remote_ws_authenticated else 'FAIL'}")
        print(f"NAV_RIGHT acknowledged:  {'PASS' if result.nav_right_acknowledged else 'FAIL'}")
        print(f"NAV_RIGHT state:         {'PASS' if result.nav_right_state_observed else 'FAIL'}")
        print(f"HOME acknowledged:       {'PASS' if result.home_acknowledged else 'FAIL'}")
        print(f"HOME state:              {'PASS' if result.home_state_observed else 'FAIL'}")
        print(f"Token revoked:           {'PASS' if result.token_revoked else 'FAIL'}")
        print("========================================\n")
        return 0
    except Exception as err:
        logger.error("Integration smoke test FAILED: %s", err)
        return 1


if __name__ == "__main__":
    sys.exit(main())
