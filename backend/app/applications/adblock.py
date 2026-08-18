from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
from typing import Any
import zipfile

import httpx

ADBLOCK_EXTENSION_ID = "gighmmpiobklfepjocnamgkkbiglidom"
ADBLOCK_DOWNLOAD_URL = (
    "https://clients2.google.com/service/update2/crx"
    "?response=redirect&prodversion=120.0&acceptformat=crx3"
    "&x=id%3Dgighmmpiobklfepjocnamgkkbiglidom%26uc"
)
ADBLOCK_DOWNLOAD_URL_FALLBACK = (
    "https://clients2.google.com/service/update2/crx"
    "?response=redirect&prodversion=128.0&acceptformat=crx3"
    "&x=id%3Dgighmmpiobklfepjocnamgkkbiglidom%26uc"
)


def compute_extension_id(key_or_manifest: dict[str, Any] | str | bytes) -> str:
    """Compute the 32-character Chrome extension ID from manifest dict, JSON, or DER key bytes."""
    der_bytes: bytes | None = None

    if isinstance(key_or_manifest, dict):
        b64_key = key_or_manifest.get("key")
        if not b64_key:
            return ""
        der_bytes = base64.b64decode(b64_key)
    elif isinstance(key_or_manifest, str):
        stripped = key_or_manifest.strip()
        if stripped.startswith("{"):
            parsed = json.loads(stripped)
            b64_key = parsed.get("key")
            if not b64_key:
                return ""
            der_bytes = base64.b64decode(b64_key)
        else:
            der_bytes = base64.b64decode(stripped)
    elif isinstance(key_or_manifest, bytes):
        stripped_b = key_or_manifest.strip()
        if stripped_b.startswith(b"{"):
            parsed = json.loads(stripped_b.decode("utf-8"))
            b64_key = parsed.get("key")
            if not b64_key:
                return ""
            der_bytes = base64.b64decode(b64_key)
        else:
            der_bytes = stripped_b

    if not der_bytes:
        return ""

    digest = hashlib.sha256(der_bytes).digest()[:16]
    return "".join(chr(ord("a") + (b >> 4)) + chr(ord("a") + (b & 0x0F)) for b in digest)


def extract_crx3_id(header_bytes: bytes) -> str | None:
    """Extract crx_id (16 bytes) from CRX3 protobuf header if present."""
    idx = 0
    while True:
        pos = header_bytes.find(b"\x0a\x10", idx)
        if pos == -1:
            break
        crx_id_bytes = header_bytes[pos + 2 : pos + 18]
        if len(crx_id_bytes) == 16:
            return "".join(chr(ord("a") + (b >> 4)) + chr(ord("a") + (b & 0x0F)) for b in crx_id_bytes)
        idx = pos + 1
    return None


def unpack_crx(crx_bytes: bytes) -> tuple[bytes, str | None]:
    """Validate CRX3 header, extract zip payload and optional extension ID from header."""
    if len(crx_bytes) < 12 or not crx_bytes.startswith(b"Cr24"):
        raise ValueError("Invalid CRX header: missing Cr24 magic number")

    version, header_size = struct.unpack("<II", crx_bytes[4:12])
    if version != 3:
        raise ValueError(f"Unsupported CRX version: {version}")

    header_end = 12 + header_size
    if len(crx_bytes) < header_end:
        raise ValueError("Invalid CRX header: payload truncated")

    header_bytes = crx_bytes[12:header_end]
    crx_id = extract_crx3_id(header_bytes)
    zip_bytes = crx_bytes[header_end:]
    return zip_bytes, crx_id


def download_adblock_crx(url: str = ADBLOCK_DOWNLOAD_URL) -> bytes:
    """Download AdBlock CRX3 file from Google Chrome update servers with fallback."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )
    }
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        resp = client.get(url, headers=headers)
        if resp.status_code == 200 and len(resp.content) >= 12:
            return resp.content

        # Fallback to newer prodversion if 204 or empty
        fallback_resp = client.get(ADBLOCK_DOWNLOAD_URL_FALLBACK, headers=headers)
        if fallback_resp.status_code == 200 and len(fallback_resp.content) >= 12:
            return fallback_resp.content

        raise ValueError(
            f"Failed to download AdBlock CRX: primary HTTP {resp.status_code}, "
            f"fallback HTTP {fallback_resp.status_code}"
        )


def ensure_adblock(directory: Path, crx_bytes: bytes | None = None) -> Path:
    """Ensure unpacked AdBlock extension exists at directory with verified ID."""
    manifest_file = directory / "manifest.json"

    if manifest_file.is_file() and crx_bytes is None:
        try:
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            computed_id = compute_extension_id(manifest_data)
            if computed_id:
                if computed_id == ADBLOCK_EXTENSION_ID:
                    return directory
                shutil.rmtree(directory, ignore_errors=True)
                raise ValueError(
                    f"Extension ID mismatch: expected {ADBLOCK_EXTENSION_ID}, got {computed_id}"
                )
            return directory
        except json.JSONDecodeError:
            shutil.rmtree(directory, ignore_errors=True)

    if crx_bytes is None:
        crx_bytes = download_adblock_crx()

    try:
        zip_bytes, header_crx_id = unpack_crx(crx_bytes)
    except ValueError:
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        raise

    temp_dir = directory.parent / f"{directory.name}.tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(temp_dir)

        unpacked_manifest = temp_dir / "manifest.json"
        if not unpacked_manifest.is_file():
            raise ValueError("Missing manifest.json after unpacking extension")

        manifest_data = json.loads(unpacked_manifest.read_text(encoding="utf-8"))
        computed_id = compute_extension_id(manifest_data)
        if not computed_id and header_crx_id:
            computed_id = header_crx_id

        if computed_id and computed_id != ADBLOCK_EXTENSION_ID:
            raise ValueError(
                f"Extension ID mismatch: expected {ADBLOCK_EXTENSION_ID}, got {computed_id}"
            )

        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        temp_dir.rename(directory)
    except Exception:
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and verify AdBlock extension for TV Chrome profile.")
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "vendor" / "adblock",
        help="Target directory for unpacked AdBlock extension",
    )
    args = parser.parse_args()
    installed = ensure_adblock(args.directory)
    print(f"AdBlock is ready at {installed}")


if __name__ == "__main__":
    main()
