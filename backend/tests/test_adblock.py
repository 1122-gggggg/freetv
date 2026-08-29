from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import struct
import zipfile

import pytest

from app.applications.adblock import (
    ADBLOCK_EXTENSION_ID,
    ADBLOCK_YOUTUBE_EXTENSION_ID,
    compute_extension_id,
    ensure_adblock,
    ensure_adblock_youtube,
    ensure_store_extension,
    ensure_tv_adblockers,
)


def _make_mock_crx3(
    manifest_dict: dict | None,
    crx_id: bytes = bytes.fromhex("6867ccf8e1ab54f9e2d0c6aa186b83ec"),
) -> bytes:
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
        if manifest_dict is not None:
            z.writestr("manifest.json", json.dumps(manifest_dict))
        z.writestr("rules.json", "[]")
    zip_bytes = zip_buf.getvalue()

    # Protobuf signed_header_data with crx_id (0x0a 0x10 + 16 bytes crx_id)
    signed_header_data = b"\x0a\x10" + crx_id
    header = b"\x12\x12" + signed_header_data
    crx_bytes = b"Cr24" + struct.pack("<II", 3, len(header)) + header + zip_bytes
    return crx_bytes


def test_compute_extension_id_from_der_bytes() -> None:
    der = b"sample der public key content for test"
    ext_id = compute_extension_id(der)
    assert len(ext_id) == 32
    assert all("a" <= c <= "p" for c in ext_id)
    assert ext_id == "mnbkkneelgpafnjbiencalgdpkjekhgg"


def test_compute_extension_id_from_manifest_dict() -> None:
    der = b"sample der public key content for test"
    b64_key = base64.b64encode(der).decode("ascii")
    manifest = {"name": "Test Extension", "version": "1.0", "key": b64_key}
    ext_id = compute_extension_id(manifest)
    assert ext_id == "mnbkkneelgpafnjbiencalgdpkjekhgg"


def test_ensure_adblock_returns_existing_valid_directory(tmp_path: Path) -> None:
    adblock_dir = tmp_path / "adblock"
    adblock_dir.mkdir()
    # Write manifest with dummy key that produces target ID or use mock
    # When manifest has no key, or when key produces target ID
    manifest_dict = {"name": "AdBlock", "version": "6.45.2"}
    (adblock_dir / "manifest.json").write_text(json.dumps(manifest_dict), encoding="utf-8")

    # If manifest doesn't have key or has key matching target ID
    # With crx_bytes provided or existing valid dir
    valid_crx = _make_mock_crx3({"name": "AdBlock", "version": "1.0"})
    result = ensure_adblock(adblock_dir, crx_bytes=valid_crx)
    assert result == adblock_dir
    assert (adblock_dir / "manifest.json").is_file()


def test_ensure_adblock_rejects_wrong_extension_id_and_deletes_directory(tmp_path: Path) -> None:
    adblock_dir = tmp_path / "adblock"
    adblock_dir.mkdir()
    der = b"wrong public key content"
    b64_key = base64.b64encode(der).decode("ascii")
    (adblock_dir / "manifest.json").write_text(
        json.dumps({"name": "Wrong", "version": "1.0", "key": b64_key}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        ensure_adblock(adblock_dir)
    assert ADBLOCK_EXTENSION_ID in str(excinfo.value)
    assert not adblock_dir.exists()


def test_ensure_adblock_rejects_missing_manifest_after_unpack_and_deletes_directory(
    tmp_path: Path,
) -> None:
    adblock_dir = tmp_path / "adblock"
    bad_crx = _make_mock_crx3(manifest_dict=None)

    with pytest.raises(ValueError) as excinfo:
        ensure_adblock(adblock_dir, crx_bytes=bad_crx)
    assert "manifest" in str(excinfo.value).lower()
    assert not adblock_dir.exists()


def test_ensure_adblock_rejects_invalid_crx_magic(tmp_path: Path) -> None:
    adblock_dir = tmp_path / "adblock"
    with pytest.raises(ValueError) as excinfo:
        ensure_adblock(adblock_dir, crx_bytes=b"not a crx file")
    assert "crx" in str(excinfo.value).lower()
    assert not adblock_dir.exists()


def test_ensure_adblock_unpacks_valid_crx_bytes_and_returns_path(tmp_path: Path) -> None:
    adblock_dir = tmp_path / "adblock"
    valid_crx = _make_mock_crx3({"name": "AdBlock", "version": "6.45.2"})

    result = ensure_adblock(adblock_dir, crx_bytes=valid_crx)
    assert result == adblock_dir
    assert adblock_dir.is_dir()
    assert (adblock_dir / "manifest.json").is_file()
    assert (adblock_dir / "rules.json").is_file()


def test_ensure_adblock_rejects_unpacked_crx_with_wrong_id(tmp_path: Path) -> None:
    adblock_dir = tmp_path / "adblock"
    wrong_crx_id = bytes.fromhex("11223344556677889900aabbccddeeff")
    wrong_crx = _make_mock_crx3({"name": "Wrong", "version": "1.0"}, crx_id=wrong_crx_id)

    with pytest.raises(ValueError) as excinfo:
        ensure_adblock(adblock_dir, crx_bytes=wrong_crx)
    assert ADBLOCK_EXTENSION_ID in str(excinfo.value)
    assert not adblock_dir.exists()


def _varint(value: int) -> bytes:
    out = bytearray()
    while value > 127:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _proto_bytes(field: int, payload: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(payload)) + payload


def _make_mock_crx3_with_public_key(
    manifest_dict: dict, public_key: bytes, extension_id: str
) -> bytes:
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest_dict))
        z.writestr("rules.json", "[]")
    zip_bytes = zip_buf.getvalue()
    crx_id = bytes(
        ((ord(extension_id[index]) - ord("a")) << 4) | (ord(extension_id[index + 1]) - ord("a"))
        for index in range(0, 32, 2)
    )
    header = _proto_bytes(2, _proto_bytes(1, public_key)) + b"\x0a\x10" + crx_id
    return b"Cr24" + struct.pack("<II", 3, len(header)) + header + zip_bytes


def test_ensure_store_extension_writes_manifest_key_from_crx_public_key(tmp_path: Path) -> None:
    public_key = b"\x30" + b"K" * 80
    extension_id = compute_extension_id(public_key)
    target = tmp_path / "ext"
    crx = _make_mock_crx3_with_public_key(
        {"name": "Store", "version": "1.0"}, public_key, extension_id
    )

    result = ensure_store_extension(target, extension_id, crx_bytes=crx)

    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["key"] == base64.b64encode(public_key).decode("ascii")
    assert compute_extension_id(manifest) == extension_id


def test_ensure_adblock_youtube_accepts_matching_store_id(tmp_path: Path) -> None:
    target = tmp_path / "adblock-youtube"
    crx_id = bytes(
        ((ord(ADBLOCK_YOUTUBE_EXTENSION_ID[index]) - ord("a")) << 4)
        | (ord(ADBLOCK_YOUTUBE_EXTENSION_ID[index + 1]) - ord("a"))
        for index in range(0, 32, 2)
    )
    crx = _make_mock_crx3({"name": "Adblock for YouTube", "version": "1.0"}, crx_id=crx_id)

    result = ensure_adblock_youtube(target, crx_bytes=crx)

    assert result == target
    assert (target / "manifest.json").is_file()


def test_ensure_tv_adblockers_installs_both_store_ids(tmp_path: Path) -> None:
    adblock = tmp_path / "adblock"
    youtube = tmp_path / "adblock-youtube"
    adblock_crx = _make_mock_crx3({"name": "AdBlock", "version": "1.0"})
    youtube_crx_id = bytes(
        ((ord(ADBLOCK_YOUTUBE_EXTENSION_ID[index]) - ord("a")) << 4)
        | (ord(ADBLOCK_YOUTUBE_EXTENSION_ID[index + 1]) - ord("a"))
        for index in range(0, 32, 2)
    )
    youtube_crx = _make_mock_crx3(
        {"name": "Adblock for YouTube", "version": "1.0"},
        crx_id=youtube_crx_id,
    )

    installed = ensure_tv_adblockers(
        adblock,
        youtube,
        adblock_crx=adblock_crx,
        youtube_crx=youtube_crx,
    )

    assert installed == (adblock, youtube)
    assert (adblock / "manifest.json").is_file()
    assert (youtube / "manifest.json").is_file()
