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
        artifact_kind="archive",
        download_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/pc-tv-box.zip",
        checksum_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.0/pc-tv-box.zip.sha256",
    )


def installer_update_info() -> UpdateInfo:
    return UpdateInfo(
        available=True,
        version="v0.4.2",
        release_name="FreeTV 0.4.2",
        release_notes="Complete installer update",
        artifact_kind="installer",
        download_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.2/FreeTV-Setup.exe",
        checksum_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.2/FreeTV-Setup.exe.sha256",
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


def test_apply_update_streams_installer_incrementally_to_destination(
    tmp_path: Path,
) -> None:
    first_chunk = b"MZ-first-"
    second_chunk = b"second"
    installer = first_chunk + second_chunk
    digest = hashlib.sha256(installer).hexdigest()
    updates = tmp_path / "config" / "updates"

    class IncrementalBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield first_chunk
            staged = list(updates.glob("FreeTV-Setup-*.tmp"))
            assert len(staged) == 1
            assert staged[0].read_bytes() == first_chunk
            yield second_chunk

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "python.exe").touch()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".sha256"):
            return httpx.Response(200, text=f"{digest}  FreeTV-Setup.exe\n")
        return httpx.Response(200, stream=IncrementalBody())

    async def stage() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await updater.apply_update(
                tmp_path, client=client, info=installer_update_info()
            )

    result = asyncio.run(stage())
    marker_path = updates / "pending-installer-update.json"
    marker = json.loads(marker_path.read_text())
    staged_installer = Path(marker["installer"])

    assert result.success
    assert result.restart_required
    assert marker["version"] == "v0.4.2"
    assert marker["sha256"] == digest
    assert staged_installer.is_relative_to(updates)
    assert staged_installer.read_bytes() == installer


def test_apply_update_rejects_oversized_installer_stream_without_marker(
    tmp_path: Path, monkeypatch
) -> None:
    class ChunkedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"MZ12"
            yield b"34567"

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "python.exe").touch()
    monkeypatch.setattr(updater, "MAX_INSTALLER_BYTES", 8)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".sha256"):
            return httpx.Response(200, text=f"{'0' * 64}  FreeTV-Setup.exe\n")
        return httpx.Response(200, stream=ChunkedBody())

    async def stage() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await updater.apply_update(
                tmp_path, client=client, info=installer_update_info()
            )

    result = asyncio.run(stage())
    updates = tmp_path / "config" / "updates"

    assert not result.success
    assert "更新檔過大" in result.message
    assert not (updates / "pending-installer-update.json").exists()
    assert list(updates.glob("*.tmp")) == []
    assert list(updates.glob("*.exe")) == []


def test_apply_update_rejects_installer_checksum_mismatch_without_marker(
    tmp_path: Path,
) -> None:
    installer = b"MZ-complete-installer"

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".sha256"):
            return httpx.Response(200, text=f"{'0' * 64}  FreeTV-Setup.exe\n")
        return httpx.Response(200, content=installer)

    async def stage() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await updater.apply_update(
                tmp_path, client=client, info=installer_update_info()
            )

    result = asyncio.run(stage())
    updates = tmp_path / "config" / "updates"

    assert not result.success
    assert "校驗失敗" in result.message
    assert not (updates / "pending-installer-update.json").exists()
    assert list(updates.glob("*.exe")) == []


def test_apply_update_rejects_untrusted_installer_redirect(tmp_path: Path) -> None:
    redirected = replace(
        installer_update_info(),
        download_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.2/redirect.exe",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/redirect.exe"):
            return httpx.Response(
                302, headers={"Location": "http://attacker.example/FreeTV-Setup.exe"}
            )
        return httpx.Response(500)

    async def stage() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await updater.apply_update(tmp_path, client=client, info=redirected)

    result = asyncio.run(stage())

    assert not result.success
    assert "不受信任" in result.message
    assert not (
        tmp_path / "config" / "updates" / "pending-installer-update.json"
    ).exists()


def test_installer_marker_staging_does_not_use_predictable_temp_name(
    tmp_path: Path,
) -> None:
    installer = b"MZ-atomic-marker"
    digest = hashlib.sha256(installer).hexdigest()
    updates = tmp_path / "config" / "updates"
    updates.mkdir(parents=True)
    predictable = updates / "pending-installer-update.tmp"
    predictable.write_text("must remain untouched")

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".sha256"):
            return httpx.Response(200, text=f"{digest}  FreeTV-Setup.exe\n")
        return httpx.Response(200, content=installer)

    async def stage() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await updater.apply_update(
                tmp_path, client=client, info=installer_update_info()
            )

    result = asyncio.run(stage())

    assert result.success
    assert predictable.read_text() == "must remain untouched"


def test_repeated_installer_stage_removes_superseded_valid_source(tmp_path: Path) -> None:
    installer = b"MZ-repeated-update"
    digest = hashlib.sha256(installer).hexdigest()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".sha256"):
            return httpx.Response(200, text=f"{digest}  FreeTV-Setup.exe\n")
        return httpx.Response(200, content=installer)

    async def stage_twice() -> tuple[object, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            first = await updater.apply_update(
                tmp_path, client=client, info=installer_update_info()
            )
            second_info = replace(
                installer_update_info(),
                version="v0.4.3",
                download_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.3/FreeTV-Setup.exe",
                checksum_url="https://github.com/1122-gggggg/freetv/releases/download/v0.4.3/FreeTV-Setup.exe.sha256",
            )
            second = await updater.apply_update(
                tmp_path, client=client, info=second_info
            )
            return first, second

    first, second = asyncio.run(stage_twice())
    marker = json.loads(
        (
            tmp_path / "config" / "updates" / "pending-installer-update.json"
        ).read_text()
    )
    current_source = Path(marker["installer"])
    staged_sources = list((tmp_path / "config" / "updates").glob("*.exe"))

    assert first.success
    assert second.success
    assert marker["version"] == "v0.4.3"
    assert staged_sources == [current_source]


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


def release_payload() -> dict[str, object]:
    base_url = "https://github.com/1122-gggggg/freetv/releases/download/v0.4.0"
    return {
        "tag_name": "v0.4.0",
        "name": "FreeTV 0.4.0",
        "body": "notes",
        "assets": [
            {
                "name": name,
                "browser_download_url": f"{base_url}/{name}",
            }
            for name in (
                "pc-tv-box.zip",
                "pc-tv-box.zip.sha256",
                "FreeTV-Setup.exe",
                "FreeTV-Setup.exe.sha256",
                "unrelated.zip",
            )
        ],
    }


def check_release(root: Path, payload: dict[str, object]) -> UpdateInfo | None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))

    async def check() -> UpdateInfo | None:
        async with httpx.AsyncClient(transport=transport) as client:
            return await updater.check_for_update(root, client=client)

    return asyncio.run(check())


def test_release_check_selects_exact_installer_assets_for_bundled_root(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(updater, "CURRENT_VERSION", "0.3.0")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "python.exe").touch()

    info = check_release(tmp_path, release_payload())

    assert info is not None
    assert info.artifact_kind == "installer"
    assert info.download_url is not None
    assert info.download_url.endswith("/FreeTV-Setup.exe")
    assert info.checksum_url is not None
    assert info.checksum_url.endswith("/FreeTV-Setup.exe.sha256")


def test_release_check_selects_exact_archive_assets_for_portable_root(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(updater, "CURRENT_VERSION", "0.3.0")

    info = check_release(tmp_path, release_payload())

    assert info is not None
    assert info.artifact_kind == "archive"
    assert info.download_url is not None
    assert info.download_url.endswith("/pc-tv-box.zip")
    assert info.checksum_url is not None
    assert info.checksum_url.endswith("/pc-tv-box.zip.sha256")


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
