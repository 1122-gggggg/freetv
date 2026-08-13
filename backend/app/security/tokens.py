from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class TokenStore:
    """Persists salted token hashes; raw remote tokens never reach disk."""

    def __init__(
        self,
        path: Path,
        *,
        token_bytes: int = 32,
        max_tokens: int = 12,
        token_ttl: timedelta = timedelta(days=90),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = path
        self._token_bytes = token_bytes
        self._max_tokens = max_tokens
        self._token_ttl = token_ttl
        self._now = now or (lambda: datetime.now(UTC))
        self._active_keys: set[bytes] | None = None

    def issue_token(self) -> str:
        token = secrets.token_urlsafe(self._token_bytes)
        token_key = self._token_key(token)
        salt = secrets.token_bytes(16)
        record = {
            "token_key": token_key.hex(),
            "salt": base64.b64encode(salt).decode("ascii"),
            "digest": base64.b64encode(self._digest(token, salt)).decode("ascii"),
            "created_at": self._now().isoformat(),
        }
        records = self._active_records()
        records.append(record)
        self._write_records(records[-self._max_tokens :])
        return token

    def verify(self, token: str) -> bool:
        return self.token_expires_at(token) is not None

    def is_token_key_active(self, token_key: bytes) -> bool:
        return token_key in self._active_token_keys()

    def token_expires_at(self, token: str) -> datetime | None:
        if not self._is_token_shape_valid(token):
            return None
        token_key = self._token_key(token)
        records = self._active_records()
        for record in records:
            if self._record_matches(token, record, token_key):
                if self._record_token_key(record) is None:
                    record["token_key"] = token_key.hex()
                    self._write_records(records)
                return self._record_expires_at(record)
        return None

    def revoke(self, token: str) -> bool:
        if not self._is_token_shape_valid(token):
            return False
        token_key = self._token_key(token)
        records = self._active_records()
        remaining = [
            record for record in records if not self._record_matches(token, record, token_key)
        ]
        if len(remaining) == len(records):
            return False
        self._write_records(remaining)
        return True

    def revoke_all(self) -> None:
        self._write_records([])

    def _active_records(self) -> list[dict[str, str]]:
        records = self._load_records()
        active = [record for record in records if self._record_is_active(record)]
        if len(active) != len(records):
            self._write_records(active)
        return active

    def _record_is_active(self, record: dict[str, str]) -> bool:
        expires_at = self._record_expires_at(record)
        return expires_at is not None and self._now() < expires_at

    def _record_expires_at(self, record: dict[str, str]) -> datetime | None:
        try:
            created_at = datetime.fromisoformat(record["created_at"])
        except (KeyError, TypeError, ValueError):
            return None
        if created_at.tzinfo is None:
            return None
        return created_at.astimezone(UTC) + self._token_ttl

    def _record_matches(self, token: str, record: dict[str, str], token_key: bytes) -> bool:
        stored_token_key = self._record_token_key(record)
        if stored_token_key is not None and not hmac.compare_digest(stored_token_key, token_key):
            return False
        try:
            salt = base64.b64decode(record["salt"], validate=True)
            expected = base64.b64decode(record["digest"], validate=True)
        except (KeyError, TypeError, ValueError):
            return False
        return hmac.compare_digest(expected, self._digest(token, salt))

    @staticmethod
    def _is_token_shape_valid(token: object) -> bool:
        return isinstance(token, str) and 32 <= len(token) <= 512

    @staticmethod
    def _digest(token: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, 210_000)

    @staticmethod
    def _token_key(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    @staticmethod
    def _record_token_key(record: dict[str, str]) -> bytes | None:
        try:
            token_key = bytes.fromhex(record["token_key"])
        except (KeyError, TypeError, ValueError):
            return None
        return token_key if len(token_key) == 32 else None

    def _active_token_keys(self) -> set[bytes]:
        if self._active_keys is None:
            self._active_keys = {
                token_key
                for record in self._active_records()
                if (token_key := self._record_token_key(record)) is not None
            }
        return self._active_keys

    def _load_records(self) -> list[dict[str, str]]:
        if not self._path.exists():
            return []
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        return [record for record in raw if isinstance(record, dict)]

    def _write_records(self, records: list[dict[str, str]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        payload = json.dumps(records, ensure_ascii=False, indent=2)
        temporary_path.write_text(payload, encoding="utf-8")
        os.replace(temporary_path, self._path)
        self._active_keys = {
            token_key
            for record in records
            if (token_key := self._record_token_key(record)) is not None
        }
