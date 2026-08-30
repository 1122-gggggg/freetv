from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.protocol import (
    Command,
    CommandMessage,
    NetflixContext,
    NetflixInputKind,
    NetflixStage,
    PointerActionMessage,
    TextInputMessage,
)
from app.security.pairing import PairingCodeExpired, PairingCodeInvalid, PairingService
from app.security.tokens import TokenStore


def test_async_token_issue_does_not_block_event_loop(tmp_path, monkeypatch) -> None:
    tokens = TokenStore(tmp_path / "remotes.json")
    original_digest = tokens._digest
    digest_started = threading.Event()
    release_digest = threading.Event()
    watchdog = threading.Timer(1, release_digest.set)

    def paused_digest(token: str, salt: bytes) -> bytes:
        digest_started.set()
        release_digest.wait()
        return original_digest(token, salt)

    monkeypatch.setattr(tokens, "_digest", paused_digest)

    async def run() -> None:
        issue = asyncio.create_task(tokens.issue_token_async())
        for _ in range(100):
            if digest_started.is_set():
                break
            await asyncio.sleep(0.001)

        assert digest_started.is_set()
        assert not issue.done()
        release_digest.set()
        await issue

    watchdog.start()
    try:
        asyncio.run(run())
    finally:
        release_digest.set()
        watchdog.cancel()


def test_pair_async_consumes_code_once_when_called_concurrently(tmp_path) -> None:
    pairing = PairingService(
        TokenStore(tmp_path / "remotes.json"), code_factory=lambda: "482731"
    )
    code = pairing.rotate_code()

    async def race() -> list[object]:
        return await asyncio.gather(
            pairing.pair_async(code), pairing.pair_async(code), return_exceptions=True
        )

    results = asyncio.run(race())

    assert sum(isinstance(result, str) for result in results) == 1
    assert sum(isinstance(result, PairingCodeInvalid) for result in results) == 1


def test_async_authentication_primes_session_validation_cache(tmp_path, monkeypatch) -> None:
    path = tmp_path / "remotes.json"
    token = TokenStore(path).issue_token()
    tokens = TokenStore(path)
    pairing = PairingService(tokens)

    session = asyncio.run(pairing.authenticate_token_async(token))
    monkeypatch.setattr(
        tokens,
        "_load_records",
        lambda: (_ for _ in ()).throw(AssertionError("session validation touched disk")),
    )

    assert session is not None
    assert pairing.session_is_valid(session)


def test_command_message_accepts_only_whitelisted_command() -> None:
    message = CommandMessage.model_validate(
        {"version": 1, "type": "command", "request_id": "request-1", "command": "NAV_UP"}
    )

    assert message.command is Command.NAV_UP


def test_command_message_rejects_unknown_command() -> None:
    with pytest.raises(ValidationError):
        CommandMessage.model_validate(
            {"version": 1, "type": "command", "request_id": "request-1", "command": "RUN_SHELL"}
        )


def test_pointer_actions_are_bounded() -> None:
    with pytest.raises(ValidationError):
        PointerActionMessage.model_validate(
            {
                "version": 1,
                "type": "pointer",
                "request_id": "request-1",
                "action": "move",
                "dx": 101,
                "dy": 0,
            }
        )


def test_text_input_removes_control_characters_without_executing_them() -> None:
    message = TextInputMessage.model_validate(
        {
            "version": 1,
            "type": "text_input",
            "request_id": "request-1",
            "text": "hello\nworld\u0000",
        }
    )

    assert message.text == "helloworld"


def test_text_input_accepts_256_characters_and_rejects_257() -> None:
    accepted = TextInputMessage.model_validate(
        {
            "version": 1,
            "type": "text_input",
            "request_id": "text-256",
            "text": "x" * 256,
        }
    )
    assert accepted.text == "x" * 256

    with pytest.raises(ValidationError):
        TextInputMessage.model_validate(
            {
                "version": 1,
                "type": "text_input",
                "request_id": "text-257",
                "text": "x" * 257,
            }
        )


def test_text_input_submit_is_backward_compatible_and_strict() -> None:
    base = {
        "version": 1,
        "type": "text_input",
        "request_id": "text-submit",
        "text": "secret",
    }
    assert TextInputMessage.model_validate(base).submit is False
    assert TextInputMessage.model_validate({**base, "submit": True}).submit is True
    for invalid in ("true", 1, None):
        with pytest.raises(ValidationError):
            TextInputMessage.model_validate({**base, "submit": invalid})


def test_netflix_context_allows_title_only_in_browse() -> None:
    context = NetflixContext(
        stage=NetflixStage.BROWSE,
        input_kind=NetflixInputKind.NONE,
        focused_title="Example",
    )
    assert context.model_dump(mode="json") == {
        "stage": "browse",
        "input_kind": "none",
        "has_error": False,
        "can_submit": False,
        "focused_title": "Example",
    }
    with pytest.raises(ValidationError):
        NetflixContext(
            stage=NetflixStage.LOGIN,
            input_kind=NetflixInputKind.PASSWORD,
            focused_title="forbidden",
        )
    with pytest.raises(ValidationError):
        NetflixContext(
            stage=NetflixStage.BROWSE,
            input_kind=NetflixInputKind.NONE,
            focused_title="x" * 121,
        )


@pytest.mark.parametrize(
    "extra_field",
    ["value", "length", "email", "password", "code", "cookie", "token"],
)
def test_netflix_context_forbids_sensitive_or_derived_fields(extra_field: str) -> None:
    payload: dict[str, object] = {
        "stage": "login",
        "input_kind": "password",
        "has_error": False,
        "can_submit": True,
        "focused_title": None,
        extra_field: 6 if extra_field == "length" else "secret",
    }
    with pytest.raises(ValidationError):
        NetflixContext.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("has_error", "false"),
        ("has_error", 0),
        ("can_submit", "true"),
        ("can_submit", 1),
    ],
)
def test_netflix_context_boolean_fields_are_strict(field: str, value: object) -> None:
    payload = {
        "stage": "unknown",
        "input_kind": "none",
        "has_error": False,
        "can_submit": False,
        "focused_title": None,
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        NetflixContext.model_validate(payload)


@pytest.mark.parametrize("extra_field", ["javascript", "selector", "url", "raw_key"])
def test_command_and_text_messages_reject_browser_control_extra_fields(
    extra_field: str,
) -> None:
    with pytest.raises(ValidationError):
        CommandMessage.model_validate(
            {
                "version": 1,
                "type": "command",
                "request_id": "command-extra",
                "command": "OK",
                extra_field: "forbidden",
            }
        )
    with pytest.raises(ValidationError):
        TextInputMessage.model_validate(
            {
                "version": 1,
                "type": "text_input",
                "request_id": "text-extra",
                "text": "safe",
                extra_field: "forbidden",
            }
        )


def test_pairing_code_issues_a_token_once(tmp_path) -> None:
    clock = datetime(2026, 8, 13, tzinfo=UTC)
    tokens = TokenStore(tmp_path / "remotes.json")
    pairing = PairingService(tokens, now=lambda: clock, code_factory=lambda: "482731")

    code = pairing.rotate_code()
    token = pairing.pair(code)

    assert code == "482731"
    assert tokens.verify(token)
    with pytest.raises(PairingCodeInvalid):
        pairing.pair(code)


def test_expired_pairing_code_is_rejected(tmp_path) -> None:
    clock = datetime(2026, 8, 13, tzinfo=UTC)
    tokens = TokenStore(tmp_path / "remotes.json")
    pairing = PairingService(
        tokens,
        ttl=timedelta(minutes=10),
        now=lambda: clock,
        code_factory=lambda: "482731",
    )
    pairing.rotate_code()
    pairing.now = lambda: clock + timedelta(minutes=11)

    with pytest.raises(PairingCodeExpired):
        pairing.pair("482731")


def test_pairing_service_rejects_non_ascii_digits_without_comparing_them(tmp_path) -> None:
    pairing = PairingService(TokenStore(tmp_path / "remotes.json"), code_factory=lambda: "482731")
    pairing.rotate_code()

    with pytest.raises(PairingCodeInvalid):
        pairing.pair("１２３４５６")


def test_token_store_persists_only_hash_material(tmp_path) -> None:
    path = tmp_path / "remotes.json"
    tokens = TokenStore(path)
    token = tokens.issue_token()

    saved = path.read_text(encoding="utf-8")

    assert token not in saved
    assert TokenStore(path).verify(token)


def test_remote_token_expires_and_is_removed_from_persistence(tmp_path) -> None:
    now = [datetime(2026, 8, 13, tzinfo=UTC)]
    path = tmp_path / "remotes.json"
    tokens = TokenStore(path, token_ttl=timedelta(days=1), now=lambda: now[0])
    token = tokens.issue_token()

    now[0] += timedelta(days=2)

    assert not tokens.verify(token)
    assert path.read_text(encoding="utf-8") == "[]"


def test_remote_token_can_be_revoked_server_side(tmp_path) -> None:
    tokens = TokenStore(tmp_path / "remotes.json")
    token = tokens.issue_token()

    assert tokens.revoke(token)
    assert not tokens.verify(token)


def test_authenticated_remote_session_becomes_invalid_after_revocation(tmp_path) -> None:
    now = [datetime(2026, 8, 13, tzinfo=UTC)]
    tokens = TokenStore(tmp_path / "remotes.json", now=lambda: now[0])
    pairing = PairingService(tokens, now=lambda: now[0])
    token = tokens.issue_token()

    session = pairing.authenticate_token(token)

    assert session is not None
    assert pairing.session_is_valid(session)
    assert pairing.revoke_token(token)
    assert not pairing.session_is_valid(session)


def test_evicted_paired_token_invalidates_its_authenticated_session(tmp_path) -> None:
    tokens = TokenStore(tmp_path / "remotes.json", max_tokens=1)
    pairing = PairingService(tokens, code_factory=lambda: "482731")
    first_token = pairing.pair(pairing.rotate_code())
    session = pairing.authenticate_token(first_token)

    assert session is not None
    assert pairing.session_is_valid(session)

    pairing.pair(pairing.rotate_code())

    assert not tokens.verify(first_token)
    assert not pairing.session_is_valid(session)


def test_authenticated_remote_session_becomes_invalid_at_token_expiry(tmp_path) -> None:
    now = [datetime(2026, 8, 13, tzinfo=UTC)]
    tokens = TokenStore(tmp_path / "remotes.json", token_ttl=timedelta(days=1), now=lambda: now[0])
    pairing = PairingService(tokens, now=lambda: now[0])
    token = tokens.issue_token()

    session = pairing.authenticate_token(token)
    now[0] += timedelta(days=2)

    assert session is not None
    assert not pairing.session_is_valid(session)


def test_fullscreen_is_a_typed_version_one_command() -> None:
    message = CommandMessage.model_validate(
        {
            "version": 1,
            "type": "command",
            "request_id": "fullscreen-1",
            "command": "FULLSCREEN",
        }
    )
    assert message.command is Command.FULLSCREEN
