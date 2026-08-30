from __future__ import annotations

import asyncio
import hashlib
import io
import json
import stat
import zipfile
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.installer import apply_pending_update
from app.state import ControllerState, StateStore
from app.system import updater
from app.system.updater import UpdateInfo, UpdateWatcher


def release_archive(extra_entries: dict[str, bytes] | None = None) -> bytes:
    entries = {
        "pc-tv-box/freetv.py": b"print('new')\n",
        "pc-tv-box/backend/app/__init__.py": b"",
        "pc-tv-box/frontend/dist/index.html": b"<div id='root'></div>",
        **(extra_entries or {}),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def update_info() -> UpdateInfo:
    return UpdateInfo(
        available=True,
        version="v0.4.0",
        release_name="FreeTV 0.4.0",
        release_notes="Safer updates",
        download_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/pc-tv-box.zip",
        checksum_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/pc-tv-box.zip.sha256",
    )


def update_client(archive: bytes, checksum: str | None = None) -> httpx.AsyncClient:
    digest = checksum or hashlib.sha256(archive).hexdigest()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".sha256"):
            return httpx.Response(200, text=f"{digest}  pc-tv-box.zip\n")
        return httpx.Response(
            200,
            content=archive,
            headers={"Content-Length": str(len(archive))},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def test_apply_update_stages_verified_release_for_next_start(tmp_path: Path) -> None:
    archive = release_archive()

    async def stage() -> object:
        async with update_client(archive) as client:
            return await updater.apply_update(tmp_path, client=client, info=update_info())

    result = asyncio.run(stage())
    marker = json.loads((tmp_path / "config" / "pending-update.json").read_text())

    assert result.success
    assert result.restart_required
    assert Path(marker["staging"]).is_relative_to(tmp_path / "config" / "updates")
    assert apply_pending_update(tmp_path)
    assert (tmp_path / "freetv.py").read_text() == "print('new')\n"


def test_apply_update_rejects_checksum_mismatch_without_marker(tmp_path: Path) -> None:
    archive = release_archive()

    async def stage() -> object:
        async with update_client(archive, checksum="0" * 64) as client:
            return await updater.apply_update(tmp_path, client=client, info=update_info())

    result = asyncio.run(stage())

    assert not result.success
    assert "校驗失敗" in result.message
    assert not (tmp_path / "config" / "pending-update.json").exists()


def test_apply_update_follows_github_style_asset_redirects(tmp_path: Path) -> None:
    archive = release_archive()
    digest = hashlib.sha256(archive).hexdigest()
    info = update_info()
    redirected = replace(
        info,
        download_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/redirect.zip",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/redirect.zip"):
            return httpx.Response(
                302,
                headers={
                    "Location": "https://release-assets.githubusercontent.com/actual.zip"
                },
            )
        if request.url.path.endswith("/actual.zip"):
            return httpx.Response(200, content=archive)
        return httpx.Response(200, text=f"{digest}  pc-tv-box.zip\n")

    async def stage() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await updater.apply_update(tmp_path, client=client, info=redirected)

    result = asyncio.run(stage())

    assert result.success


def test_apply_update_rejects_redirects_outside_trusted_https_hosts(tmp_path: Path) -> None:
    info = replace(
        update_info(),
        download_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/redirect.zip",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/redirect.zip"):
            return httpx.Response(302, headers={"Location": "http://attacker.example/update.zip"})
        return httpx.Response(500)

    async def stage() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await updater.apply_update(tmp_path, client=client, info=info)

    result = asyncio.run(stage())

    assert not result.success
    assert "不受信任" in result.message


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../outside.txt",
        "/absolute.txt",
        "C:/Windows/system.ini",
        "pc-tv-box/../../outside.txt",
        "other-root/file.txt",
    ],
)
def test_archive_validation_rejects_unsafe_paths(unsafe_name: str) -> None:
    with pytest.raises(ValueError, match="不安全路徑"):
        updater._validate_archive(release_archive({unsafe_name: b"unsafe"}))


def test_archive_validation_rejects_symlinks() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in {
            "pc-tv-box/freetv.py": b"",
            "pc-tv-box/backend/app/__init__.py": b"",
            "pc-tv-box/frontend/dist/index.html": b"",
        }.items():
            archive.writestr(name, content)
        link = zipfile.ZipInfo("pc-tv-box/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "../../outside")

    with pytest.raises(ValueError, match="不安全路徑"):
        updater._validate_archive(output.getvalue())


def test_archive_validation_bounds_total_uncompressed_size(monkeypatch) -> None:
    monkeypatch.setattr(updater, "MAX_ARCHIVE_BYTES", 1_024)

    with pytest.raises(ValueError, match="內容過大"):
        updater._validate_archive(
            release_archive(
                {
                    "pc-tv-box/a.txt": b"a" * 600,
                    "pc-tv-box/b.txt": b"b" * 600,
                }
            )
        )


def test_release_check_requires_exact_archive_and_checksum_assets(monkeypatch) -> None:
    monkeypatch.setattr(updater, "CURRENT_VERSION", "0.3.0")
    payload = {
        "tag_name": "v0.4.0",
        "name": "FreeTV 0.4.0",
        "body": "notes",
        "assets": [
            {
                "name": "pc-tv-box.zip",
                "browser_download_url": "https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/pc-tv-box.zip",
            },
            {
                "name": "pc-tv-box.zip.sha256",
                "browser_download_url": "https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/pc-tv-box.zip.sha256",
            },
            {
                "name": "unrelated.zip",
                "browser_download_url": "https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/unrelated.zip",
            },
        ],
    }
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))

    async def check() -> UpdateInfo | None:
        async with httpx.AsyncClient(transport=transport) as client:
            return await updater.check_for_update(client=client)

    info = asyncio.run(check())

    assert info is not None
    assert info.download_url == (
        "https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/pc-tv-box.zip"
    )
    assert info.checksum_url == (
        "https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/pc-tv-box.zip.sha256"
    )


def test_update_watcher_publishes_new_state(monkeypatch) -> None:
    info = update_info()
    published: list[UpdateInfo | None] = []
    sleep_calls = 0

    async def check() -> UpdateInfo:
        return info

    async def stop_after_one_iteration(_: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls > 1:
            raise asyncio.CancelledError

    async def publish(value: UpdateInfo | None) -> None:
        published.append(value)

    monkeypatch.setattr(updater, "check_for_update", check)
    monkeypatch.setattr(updater.asyncio, "sleep", stop_after_one_iteration)
    state = StateStore(ControllerState())
    watcher = UpdateWatcher(state, on_change=publish)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(watcher._run())

    assert asyncio.run(state.snapshot()).update_available == "v0.4.0"
    assert published == [info]
