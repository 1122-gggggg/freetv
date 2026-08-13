from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.protocol import Command, CommandMessage, PointerActionMessage, TextInputMessage
from app.security.pairing import PairingCodeExpired, PairingCodeInvalid, PairingService
from app.security.tokens import TokenStore


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
            {"version": 1, "type": "pointer", "request_id": "request-1", "action": "move", "dx": 101, "dy": 0}
        )


def test_text_input_removes_control_characters_without_executing_them() -> None:
    message = TextInputMessage.model_validate(
        {"version": 1, "type": "text_input", "request_id": "request-1", "text": "hello\nworld\u0000"}
    )

    assert message.text == "helloworld"


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


def test_token_store_persists_only_hash_material(tmp_path) -> None:
    path = tmp_path / "remotes.json"
    tokens = TokenStore(path)
    token = tokens.issue_token()

    saved = path.read_text(encoding="utf-8")

    assert token not in saved
    assert TokenStore(path).verify(token)
