from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class TokenStore:
    """Persists salted token hashes; raw remote tokens never reach disk."""

    def __init__(self, path: Path, *, token_bytes: int = 32, max_tokens: int = 12) -> None:
        self._path = path
        self._token_bytes = token_bytes
        self._max_tokens = max_tokens

    def issue_token(self) -> str:
        token = secrets.token_urlsafe(self._token_bytes)
        salt = secrets.token_bytes(16)
        record = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "digest": base64.b64encode(self._digest(token, salt)).decode("ascii"),
            "created_at": datetime.now(UTC).isoformat(),
        }
        records = self._load_records()
        records.append(record)
        self._write_records(records[-self._max_tokens :])
        return token

    def verify(self, token: str) -> bool:
        if not isinstance(token, str) or not 32 <= len(token) <= 512:
            return False
        for record in self._load_records():
            try:
                salt = base64.b64decode(record["salt"], validate=True)
                expected = base64.b64decode(record["digest"], validate=True)
            except (KeyError, TypeError, ValueError):
                continue
            if hmac.compare_digest(expected, self._digest(token, salt)):
                return True
        return False

    @staticmethod
    def _digest(token: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, 210_000)

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
