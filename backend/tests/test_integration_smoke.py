from __future__ import annotations

import asyncio
import importlib.util
import re
import ssl
import sys
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any

import pytest

from app.security.tls import ensure_tls_materials


def _load_smoke_module():
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "integration-smoke.py"
    module_name = "integration_smoke"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module

smoke = _load_smoke_module()


def test_connect_ws_uses_protocol_origin_without_duplicate_host_headers(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    expected_connection = object()

    async def fake_connect(
        uri: str,
        *,
        ssl: ssl.SSLContext,
        open_timeout: float,
        close_timeout: float,
        origin: str | None = None,
        additional_headers: dict[str, str] | None = None,
    ) -> object:
        captured.update(
            uri=uri,
            ssl=ssl,
            open_timeout=open_timeout,
            close_timeout=close_timeout,
            origin=origin,
            additional_headers=additional_headers,
        )
        return expected_connection

    monkeypatch.setattr(smoke.websockets, "connect", fake_connect)
    context = ssl.create_default_context()

    connection = asyncio.run(
        smoke.connect_ws(
            "wss://192.168.1.44:8765/ws/remote",
            ssl_context=context,
            headers={
                "Host": "192.168.1.44:8765",
                "Origin": "https://192.168.1.44:8765",
                "X-Smoke-Test": "yes",
            },
            timeout=3.0,
        )
    )

    assert connection is expected_connection
    assert captured == {
        "uri": "wss://192.168.1.44:8765/ws/remote",
        "ssl": context,
        "open_timeout": 3.0,
        "close_timeout": 3.0,
        "origin": "https://192.168.1.44:8765",
        "additional_headers": {"X-Smoke-Test": "yes"},
    }


def test_validate_host_address_accepts_valid_loopback_and_ipv4() -> None:
    assert smoke.validate_host_address("127.0.0.1") == "127.0.0.1"
    assert smoke.validate_host_address("localhost") == "localhost"
    assert smoke.validate_host_address("::1") == "::1"
    assert smoke.validate_host_address("192.168.1.100") == "192.168.1.100"
    assert smoke.validate_host_address("10.0.0.1") == "10.0.0.1"
    assert smoke.validate_host_address("172.16.2.15") == "172.16.2.15"


def test_validate_host_address_rejects_invalid_hosts() -> None:
    with pytest.raises(smoke.SmokeValidationError, match="non-empty string"):
        smoke.validate_host_address("")

    with pytest.raises(smoke.SmokeValidationError, match="non-empty string"):
        smoke.validate_host_address(None)  # type: ignore[arg-type]

    with pytest.raises(smoke.SmokeValidationError, match="Invalid host address"):
        smoke.validate_host_address("my-desktop-pc.lan")

    with pytest.raises(smoke.SmokeValidationError, match="Invalid host address"):
        smoke.validate_host_address("999.999.999.999")

    with pytest.raises(smoke.SmokeValidationError, match="IPv6"):
        smoke.validate_host_address("fe80::1")


def test_validate_port_accepts_valid_ranges() -> None:
    assert smoke.validate_port(8765) == 8765
    assert smoke.validate_port("8765") == 8765
    assert smoke.validate_port(80) == 80
    assert smoke.validate_port(443) == 443
    assert smoke.validate_port(65535) == 65535


def test_validate_port_rejects_out_of_bounds_or_malformed() -> None:
    with pytest.raises(smoke.SmokeValidationError, match="between 1 and 65535"):
        smoke.validate_port(0)

    with pytest.raises(smoke.SmokeValidationError, match="between 1 and 65535"):
        smoke.validate_port(-1)

    with pytest.raises(smoke.SmokeValidationError, match="between 1 and 65535"):
        smoke.validate_port(65536)

    with pytest.raises(smoke.SmokeValidationError, match="Port must be an integer"):
        smoke.validate_port("not-a-port")


def test_parse_and_validate_remote_url_valid_https() -> None:
    scheme, host, port = smoke.parse_and_validate_remote_url("https://192.168.1.42:8765/remote")
    assert scheme == "https"
    assert host == "192.168.1.42"
    assert port == 8765

    scheme_default, host_default, port_default = smoke.parse_and_validate_remote_url(
        "https://10.0.0.5/remote"
    )
    assert scheme_default == "https"
    assert host_default == "10.0.0.5"
    assert port_default == 443

    scheme_http, host_http, port_http = smoke.parse_and_validate_remote_url(
        "http://192.168.1.42:8765/remote"
    )
    assert (scheme_http, host_http, port_http) == ("http", "192.168.1.42", 8765)


def test_parse_and_validate_remote_url_rejects_insecure_scheme_or_invalid_host() -> None:
    with pytest.raises(smoke.SmokeValidationError, match="must be 'http' or 'https'"):
        smoke.parse_and_validate_remote_url("ftp://192.168.1.42:8765/remote")

    with pytest.raises(smoke.SmokeValidationError, match="Invalid host address"):
        smoke.parse_and_validate_remote_url("https://controller.local:8765/remote")

    with pytest.raises(smoke.SmokeValidationError, match="non-empty string"):
        smoke.parse_and_validate_remote_url("")


def test_create_request_id_matches_protocol_pattern() -> None:
    req_id = smoke.create_request_id("smoke-test")
    assert re.match(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$", req_id)
    assert req_id.startswith("smoke-test-")

    another_id = smoke.create_request_id("smoke-test")
    assert req_id != another_id


def test_build_auth_message_valid() -> None:
    token = "a" * 64
    msg = smoke.build_auth_message(token, "auth-123")
    assert msg == {
        "version": 1,
        "type": "authenticate",
        "request_id": "auth-123",
        "token": token,
    }


def test_build_auth_message_rejects_short_or_invalid_token() -> None:
    with pytest.raises(smoke.SmokeValidationError, match="between 32 and 512 characters"):
        smoke.build_auth_message("too-short")

    with pytest.raises(smoke.SmokeValidationError, match="between 32 and 512 characters"):
        smoke.build_auth_message("")

    with pytest.raises(smoke.SmokeValidationError, match="between 32 and 512 characters"):
        smoke.build_auth_message(12345)  # type: ignore[arg-type]


def test_build_command_message_valid() -> None:
    msg_nav = smoke.build_command_message("NAV_RIGHT", "nav-1")
    assert msg_nav == {
        "version": 1,
        "type": "command",
        "request_id": "nav-1",
        "command": "NAV_RIGHT",
    }

    msg_home = smoke.build_command_message("HOME", "home-1")
    assert msg_home == {
        "version": 1,
        "type": "command",
        "request_id": "home-1",
        "command": "HOME",
    }


def test_build_command_message_rejects_unknown_command() -> None:
    with pytest.raises(smoke.SmokeValidationError, match="Invalid command"):
        smoke.build_command_message("UNKNOWN_COMMAND")


def test_validate_acknowledgement_success_and_matching_id() -> None:
    ack_msg = {
        "version": 1,
        "type": "ack",
        "request_id": "req-999",
        "success": True,
        "error_code": None,
        "message": None,
    }
    smoke.validate_acknowledgement(ack_msg, "req-999", expect_success=True)


def test_validate_acknowledgement_mismatched_id_raises() -> None:
    ack_msg = {
        "version": 1,
        "type": "ack",
        "request_id": "req-other",
        "success": True,
        "error_code": None,
        "message": None,
    }
    with pytest.raises(smoke.SmokeValidationError, match="Expected request_id 'req-999'"):
        smoke.validate_acknowledgement(ack_msg, "req-999")


def test_validate_acknowledgement_unexpected_failure_raises() -> None:
    ack_msg = {
        "version": 1,
        "type": "ack",
        "request_id": "req-1",
        "success": False,
        "error_code": "command_failed",
        "message": "Error details",
    }
    with pytest.raises(smoke.SmokeValidationError, match="Expected success=True"):
        smoke.validate_acknowledgement(ack_msg, "req-1", expect_success=True)


def test_validate_acknowledgement_invalid_structure_raises() -> None:
    with pytest.raises(smoke.SmokeValidationError, match="Expected dict message"):
        smoke.validate_acknowledgement("not-a-dict", "req-1")  # type: ignore[arg-type]

    with pytest.raises(smoke.SmokeValidationError, match="Expected protocol version 1"):
        smoke.validate_acknowledgement(
            {"version": 2, "type": "ack", "request_id": "req-1", "success": True},
            "req-1",
        )

    with pytest.raises(smoke.SmokeValidationError, match="Expected message type 'ack'"):
        smoke.validate_acknowledgement(
            {"version": 1, "type": "error", "request_id": "req-1", "success": True},
            "req-1",
        )


def test_validate_state_valid_structure() -> None:
    state_msg: dict[str, Any] = {
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
    }
    smoke.validate_state(state_msg, expected_active_app="launcher", expected_focused_tile="youtube")


def test_validate_state_mismatched_app_or_tile_raises() -> None:
    state_msg: dict[str, Any] = {
        "version": 1,
        "type": "state",
        "active_app": "launcher",
        "focused_tile": "youtube",
        "volume": 50,
        "muted": False,
    }
    with pytest.raises(smoke.SmokeValidationError, match="Expected active_app 'live_tv'"):
        smoke.validate_state(state_msg, expected_active_app="live_tv")

    with pytest.raises(smoke.SmokeValidationError, match="Expected focused_tile 'netflix'"):
        smoke.validate_state(state_msg, expected_focused_tile="netflix")


def test_validate_state_invalid_types_raises() -> None:
    invalid_volume = {
        "version": 1,
        "type": "state",
        "active_app": "launcher",
        "focused_tile": "youtube",
        "volume": 150,
        "muted": False,
    }
    with pytest.raises(smoke.SmokeValidationError, match="Invalid volume"):
        smoke.validate_state(invalid_volume)

    invalid_muted = {
        "version": 1,
        "type": "state",
        "active_app": "launcher",
        "focused_tile": "youtube",
        "volume": 50,
        "muted": "not-a-bool",
    }
    with pytest.raises(smoke.SmokeValidationError, match="Invalid muted"):
        smoke.validate_state(invalid_muted)


def test_build_ssl_context_raises_for_missing_ca_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "nonexistent-ca.cer"
    with pytest.raises(smoke.SmokeValidationError, match="CA certificate file does not exist"):
        smoke.build_ssl_context(missing_path)


def test_build_ssl_context_accepts_valid_der_ca_file(tmp_path: Path) -> None:
    materials = ensure_tls_materials(tmp_path / "tls", {IPv4Address("127.0.0.1")})
    ctx = smoke.build_ssl_context(materials.ca_certificate)
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_build_ssl_context_accepts_valid_pem_ca_file(tmp_path: Path) -> None:
    materials = ensure_tls_materials(tmp_path / "tls", {IPv4Address("127.0.0.1")})
    pem_path = tmp_path / "ca.pem"
    pem_path.write_text(
        ssl.DER_cert_to_PEM_cert(materials.ca_certificate.read_bytes()),
        encoding="utf-8",
    )
    ctx = smoke.build_ssl_context(pem_path)
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_build_ssl_context_rejects_invalid_ca_files(tmp_path: Path) -> None:
    invalid_der = tmp_path / "invalid.cer"
    invalid_der.write_bytes(b"not-a-valid-der-certificate")
    with pytest.raises(smoke.SmokeValidationError, match="Failed to load CA certificate"):
        smoke.build_ssl_context(invalid_der)

    invalid_pem = tmp_path / "invalid.pem"
    invalid_pem.write_text(
        "-----BEGIN CERTIFICATE-----\nnot-a-valid-pem\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    with pytest.raises(smoke.SmokeValidationError, match="Failed to load CA certificate"):
        smoke.build_ssl_context(invalid_pem)

    empty_cert = tmp_path / "empty.cer"
    empty_cert.write_bytes(b"")
    with pytest.raises(smoke.SmokeValidationError, match="Failed to load CA certificate"):
        smoke.build_ssl_context(empty_cert)


def test_smoke_config_and_result_dataclasses() -> None:
    cfg = smoke.SmokeConfig()
    assert cfg.port == 8765
    assert cfg.loopback_host == "127.0.0.1"
    assert cfg.lan_host is None
    assert cfg.timeout == 10.0

    res = smoke.SmokeResult()
    assert not res.all_passed

    res.health_ok = True
    res.pairing_code_retrieved = True
    res.paired = True
    res.tv_ws_connected = True
    res.remote_ws_authenticated = True
    res.nav_right_acknowledged = True
    res.nav_right_state_observed = True
    res.home_acknowledged = True
    res.home_state_observed = True
    res.token_revoked = True
    assert res.all_passed
