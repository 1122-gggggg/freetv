from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.security.tokens import TokenStore


class PairingCodeInvalid(ValueError):
    pass


class PairingCodeExpired(ValueError):
    pass


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
        if len(code) != 6 or not code.isdecimal():
            raise ValueError("Pairing codes must be exactly six decimal digits.")
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
        if not isinstance(submitted_code, str) or not hmac.compare_digest(self._code, submitted_code):
            raise PairingCodeInvalid("Pairing code is invalid.")

        self._code = None
        self._expires_at = None
        return self._tokens.issue_token()

    @staticmethod
    def _generate_code() -> str:
        return f"{secrets.randbelow(900_000) + 100_000:06d}"
