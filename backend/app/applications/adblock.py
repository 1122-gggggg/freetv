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
ADBLOCK_YOUTUBE_EXTENSION_ID = "cmedhionkhpnakcndndgjdbohmhepckk"


def store_crx_url(extension_id: str, prodversion: str = "120.0") -> str:
    return (
        "https://clients2.google.com/service/update2/crx"
        f"?response=redirect&prodversion={prodversion}&acceptformat=crx3"
        f"&x=id%3D{extension_id}%26uc"
    )


ADBLOCK_DOWNLOAD_URL = store_crx_url(ADBLOCK_EXTENSION_ID)
ADBLOCK_DOWNLOAD_URL_FALLBACK = store_crx_url(ADBLOCK_EXTENSION_ID, "128.0")


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


def _read_varint(buffer: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(buffer):
        byte = buffer[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            break
    raise ValueError("Invalid CRX header: truncated protobuf varint")


def _read_protobuf_bytes_fields(buffer: bytes, field_number: int) -> list[bytes]:
    values: list[bytes] = []
    offset = 0
    while offset < len(buffer):
        key, offset = _read_varint(buffer, offset)
        number = key >> 3
        wire_type = key & 0x07
        if wire_type == 0:
            _, offset = _read_varint(buffer, offset)
        elif wire_type == 1:
            offset += 8
        elif wire_type == 2:
            length, offset = _read_varint(buffer, offset)
            payload = buffer[offset : offset + length]
            offset += length
            if number == field_number:
                values.append(payload)
        elif wire_type == 5:
            offset += 4
        else:
            break
    return values


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


def extract_crx3_public_key(
    header_bytes: bytes,
    extension_id: str | None = None,
) -> bytes | None:
    """Extract a store public key from a CRX3 header, preferring the official ID."""
    candidates: list[bytes] = []
    for field_number in (2, 3):
        for proof in _read_protobuf_bytes_fields(header_bytes, field_number):
            for key in _read_protobuf_bytes_fields(proof, 1):
                if len(key) >= 64 and key.startswith(b"\x30"):
                    candidates.append(key)
    if extension_id:
        for key in candidates:
            if compute_extension_id(key) == extension_id:
                return key
    header_id = extract_crx3_id(header_bytes)
    if header_id:
        for key in candidates:
            if compute_extension_id(key) == header_id:
                return key
    return candidates[0] if candidates else None


def unpack_crx(
    crx_bytes: bytes,
    extension_id: str | None = None,
) -> tuple[bytes, str | None, bytes | None]:
    """Validate CRX3 header, extract zip payload, ID, and optional public key."""
    if len(crx_bytes) < 12 or not crx_bytes.startswith(b"Cr24"):
        raise ValueError("Invalid CRX header: missing Cr24 magic number")

    version, header_size = struct.unpack("<II", crx_bytes[4:12])
    if version != 3:
        raise ValueError(f"Unsupported CRX version: {version}")

    header_end = 12 + header_size
    if len(crx_bytes) < header_end:
        raise ValueError("Invalid CRX header: payload truncated")

    header_bytes = crx_bytes[12:header_end]
    return (
        crx_bytes[header_end:],
        extract_crx3_id(header_bytes),
        extract_crx3_public_key(header_bytes, extension_id),
    )


def download_store_crx(extension_id: str) -> bytes:
    """Download a Chrome Web Store CRX3 from Google's update servers with fallback."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )
    }
    primary = store_crx_url(extension_id)
    fallback = store_crx_url(extension_id, "128.0")
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        resp = client.get(primary, headers=headers)
        if resp.status_code == 200 and len(resp.content) >= 12:
            return resp.content

        fallback_resp = client.get(fallback, headers=headers)
        if fallback_resp.status_code == 200 and len(fallback_resp.content) >= 12:
            return fallback_resp.content

        raise ValueError(
            f"Failed to download CRX {extension_id}: primary HTTP {resp.status_code}, "
            f"fallback HTTP {fallback_resp.status_code}"
        )


def download_adblock_crx(url: str = ADBLOCK_DOWNLOAD_URL) -> bytes:
    """Download AdBlock CRX3 file from Google Chrome update servers with fallback."""
    if url == ADBLOCK_DOWNLOAD_URL:
        return download_store_crx(ADBLOCK_EXTENSION_ID)
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

        fallback_resp = client.get(ADBLOCK_DOWNLOAD_URL_FALLBACK, headers=headers)
        if fallback_resp.status_code == 200 and len(fallback_resp.content) >= 12:
            return fallback_resp.content

        raise ValueError(
            f"Failed to download AdBlock CRX: primary HTTP {resp.status_code}, "
            f"fallback HTTP {fallback_resp.status_code}"
        )


def ensure_store_extension(
    directory: Path,
    extension_id: str,
    crx_bytes: bytes | None = None,
) -> Path:
    """Ensure an unpacked Chrome Web Store extension exists with the verified ID."""
    manifest_file = directory / "manifest.json"

    if manifest_file.is_file() and crx_bytes is None:
        try:
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            computed_id = compute_extension_id(manifest_data)
            if computed_id == extension_id:
                return directory
            if computed_id:
                shutil.rmtree(directory, ignore_errors=True)
                raise ValueError(
                    f"Extension ID mismatch: expected {extension_id}, got {computed_id}"
                )
        except json.JSONDecodeError:
            shutil.rmtree(directory, ignore_errors=True)

    if crx_bytes is None:
        crx_bytes = download_store_crx(extension_id)

    try:
        zip_bytes, header_crx_id, public_key = unpack_crx(crx_bytes, extension_id)
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
        if public_key and not manifest_data.get("key"):
            key_id = compute_extension_id(public_key)
            if key_id == extension_id:
                manifest_data["key"] = base64.b64encode(public_key).decode("ascii")
                unpacked_manifest.write_text(
                    json.dumps(manifest_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        computed_id = compute_extension_id(manifest_data)
        if not computed_id and header_crx_id:
            computed_id = header_crx_id

        if computed_id and computed_id != extension_id:
            raise ValueError(
                f"Extension ID mismatch: expected {extension_id}, got {computed_id}"
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


def ensure_adblock(directory: Path, crx_bytes: bytes | None = None) -> Path:
    """Ensure unpacked AdBlock extension exists at directory with verified ID."""
    return ensure_store_extension(directory, ADBLOCK_EXTENSION_ID, crx_bytes)


def ensure_adblock_youtube(directory: Path, crx_bytes: bytes | None = None) -> Path:
    """Ensure unpacked Adblock for YouTube exists at directory with verified ID."""
    return ensure_store_extension(directory, ADBLOCK_YOUTUBE_EXTENSION_ID, crx_bytes)


def ensure_tv_adblockers(
    adblock_directory: Path,
    youtube_directory: Path,
    adblock_crx: bytes | None = None,
    youtube_crx: bytes | None = None,
) -> tuple[Path, Path]:
    """Install both official store ad blockers used by the TV Chrome profile."""
    return (
        ensure_adblock(adblock_directory, adblock_crx),
        ensure_adblock_youtube(youtube_directory, youtube_crx),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="下載並驗證電視 Chrome 設定檔使用的 AdBlock 擴充功能。")
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "vendor" / "adblock",
        help="解壓後 AdBlock 擴充功能的目標目錄",
    )
    parser.add_argument(
        "--youtube-directory",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "vendor" / "adblock-youtube",
        help="解壓後 Adblock for YouTube 擴充功能的目標目錄",
    )
    args = parser.parse_args()
    adblock_dir, youtube_dir = ensure_tv_adblockers(args.directory, args.youtube_directory)
    print(f"AdBlock 已就緒：{adblock_dir}")
    print(f"Adblock for YouTube 已就緒：{youtube_dir}")


if __name__ == "__main__":
    main()
