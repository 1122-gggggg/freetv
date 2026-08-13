from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.security.tokens import TokenStore


class PairingCodeInvalid(ValueError):
    pass


class PairingCodeExpired(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AuthenticatedRemoteSession:
    token_key: bytes
    expires_at: datetime


class PairingService:
    def __init__(
        self,
        tokens: TokenStore,
        *,
        ttl: timedelta = timedelta(minutes=10),
        now: Callable[[], datetime] | None = None,
        code_factory: Callable[[], str] | None = None,
    ) -> None:
        self._tokens = tokens
        self._ttl = ttl
        self.now = now or (lambda: datetime.now(UTC))
        self._code_factory = code_factory or self._generate_code
        self._code: str | None = None
        self._expires_at: datetime | None = None

    def rotate_code(self) -> str:
        code = self._code_factory()
        if not _is_ascii_pairing_code(code):
            raise ValueError("Pairing codes must be exactly six ASCII digits.")
        self._code = code
        self._expires_at = self.now() + self._ttl
        return code

    def current_code(self) -> tuple[str, datetime]:
        if self._code is None or self._expires_at is None or self.now() >= self._expires_at:
            self.rotate_code()
        assert self._code is not None
        assert self._expires_at is not None
        return self._code, self._expires_at

    def pair(self, submitted_code: str) -> str:
        if self._code is None or self._expires_at is None:
            raise PairingCodeInvalid("No pairing code has been generated.")
        if self.now() >= self._expires_at:
            self._code = None
            self._expires_at = None
            raise PairingCodeExpired("Pairing code expired.")
        if not _is_ascii_pairing_code(submitted_code) or not hmac.compare_digest(
            self._code, submitted_code
        ):
            raise PairingCodeInvalid("Pairing code is invalid.")

        self._code = None
        self._expires_at = None
        return self._tokens.issue_token()

    def verify_token(self, token: str) -> bool:
        return self._tokens.verify(token)

    def authenticate_token(self, token: str) -> AuthenticatedRemoteSession | None:
        expires_at = self._tokens.token_expires_at(token)
        if expires_at is None:
            return None
        return AuthenticatedRemoteSession(self._token_key(token), expires_at)

    def session_is_valid(self, session: AuthenticatedRemoteSession) -> bool:
        return self.now() < session.expires_at and self._tokens.is_token_key_active(
            session.token_key
        )

    def revoke_token(self, token: str) -> bool:
        return self._tokens.revoke(token)

    @staticmethod
    def _token_key(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    @staticmethod
    def _generate_code() -> str:
        return f"{secrets.randbelow(900_000) + 100_000:06d}"


def _is_ascii_pairing_code(value: object) -> bool:
    return isinstance(value, str) and len(value) == 6 and value.isascii() and value.isdecimal()
