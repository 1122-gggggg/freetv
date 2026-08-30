from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import stat
import tempfile
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import project_root
from app.logging import log_event
from app.state import StateStore

logger = logging.getLogger(__name__)
GITHUB_REPO = "1122-gggggg/freetv"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
TRUSTED_UPDATE_HOSTS = frozenset(
    {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)


def _version() -> str:
    try:
        return (Path(__file__).resolve().parents[3] / "VERSION").read_text().strip()
    except OSError:
        return "0.0.0"


CURRENT_VERSION = _version()


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    available: bool
    version: str
    release_name: str
    release_notes: str
    download_url: str | None = None
    checksum_url: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateResult:
    success: bool
    message: str
    version: str | None = None
    restart_required: bool = False


def parse_version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.lstrip("vV").split("."))
    except (ValueError, TypeError):
        return (0,)


def _require_trusted_update_url(value: str) -> None:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("更新下載位址無效") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in TRUSTED_UPDATE_HOSTS
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("更新下載位址不受信任")


async def check_for_update(*, client: httpx.AsyncClient | None = None) -> UpdateInfo | None:
    own = client is None
    http = client or httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "FreeTV-Appliance"})
    try:
        response = await http.get(GITHUB_API_URL)
        if response.status_code != 200:
            return None
        payload = response.json()
        tag = str(payload.get("tag_name") or "").strip()
        found = {}
        for asset in (
            payload.get("assets", []) if isinstance(payload.get("assets", []), list) else []
        ):
            if isinstance(asset, dict) and asset.get("name") in (
                "pc-tv-box.zip",
                "pc-tv-box.zip.sha256",
            ):
                found[asset["name"]] = str(asset.get("browser_download_url") or "")
        if (
            tag
            and parse_version(tag) > parse_version(CURRENT_VERSION)
            and all(found.get(x) for x in ("pc-tv-box.zip", "pc-tv-box.zip.sha256"))
        ):
            _require_trusted_update_url(found["pc-tv-box.zip"])
            _require_trusted_update_url(found["pc-tv-box.zip.sha256"])
            return UpdateInfo(
                True,
                tag,
                str(payload.get("name") or tag),
                str(payload.get("body") or "")[:500],
                found["pc-tv-box.zip"],
                found["pc-tv-box.zip.sha256"],
            )
    except Exception as error:
        log_event(logger, "update_check_failed", error=str(error))
    finally:
        if own:
            await http.aclose()
    return None


def _validate_archive(data: bytes) -> list[zipfile.ZipInfo]:
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("更新檔過大")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
    total_size = 0
    for info in infos:
        name = info.filename.replace("\\", "/")
        p = Path(name)
        if (
            not name.startswith("pc-tv-box/")
            or ":" in name
            or p.is_absolute()
            or ".." in p.parts
            or (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK
        ):
            raise ValueError("更新檔包含不安全路徑")
        total_size += info.file_size
        if (
            total_size > MAX_ARCHIVE_BYTES
            or info.file_size > MAX_ARCHIVE_BYTES
            or info.compress_size > MAX_ARCHIVE_BYTES
        ):
            raise ValueError("更新檔內容過大")
    names = {x.filename.rstrip("/") for x in infos}
    if (
        "pc-tv-box/freetv.py" not in names
        or not any(x.startswith("pc-tv-box/backend/app/") for x in names)
        or not any(x.startswith("pc-tv-box/frontend/dist/") for x in names)
    ):
        raise ValueError("更新檔結構無效")
    return infos


async def _download_limited(
    client: httpx.AsyncClient,
    url: str,
    *,
    maximum_bytes: int,
) -> bytes:
    payload = bytearray()
    _require_trusted_update_url(url)
    async with client.stream("GET", url, follow_redirects=True) as response:
        for redirect in response.history:
            _require_trusted_update_url(str(redirect.url))
        _require_trusted_update_url(str(response.url))
        if response.status_code != 200:
            raise ValueError("更新下載失敗")
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError as error:
                raise ValueError("更新下載資訊無效") from error
            if declared_size < 0 or declared_size > maximum_bytes:
                raise ValueError("更新檔過大")
        async for chunk in response.aiter_bytes():
            if len(payload) + len(chunk) > maximum_bytes:
                raise ValueError("更新檔過大")
            payload.extend(chunk)
    return bytes(payload)


async def apply_update(
    root: Path | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    info: UpdateInfo | None = None,
) -> UpdateResult:
    base = root or project_root()
    info = info or await check_for_update(client=client)
    if not info or not info.download_url or not info.checksum_url:
        return UpdateResult(False, "找不到可用的正式版本更新。")
    own = client is None
    http = client or httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    staging_container: Path | None = None
    marker_tmp: Path | None = None
    try:
        archive = await _download_limited(
            http,
            info.download_url,
            maximum_bytes=MAX_DOWNLOAD_BYTES,
        )
        checksum_payload = await _download_limited(
            http,
            info.checksum_url,
            maximum_bytes=4_096,
        )
        checksum = checksum_payload.decode("ascii", errors="strict").strip().split()[0]
        if (
            len(archive) > MAX_DOWNLOAD_BYTES
            or len(checksum) != 64
            or hashlib.sha256(archive).hexdigest().lower() != checksum.lower()
        ):
            raise ValueError("更新檔校驗失敗")
        _validate_archive(archive)
        parent = base / "config" / "updates"
        if (base / "config").is_symlink() or parent.is_symlink():
            raise ValueError("更新暫存目錄不安全")
        parent.mkdir(parents=True, exist_ok=True)
        safe_version = (
            "".join(c if c.isalnum() or c in ".-_" else "_" for c in info.version)[:80] or "update"
        )
        staging_container = Path(tempfile.mkdtemp(prefix=f"{safe_version}-", dir=parent))
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            zf.extractall(staging_container)
        staging = staging_container / "pc-tv-box"
        marker = base / "config" / "pending-update.json"
        marker.parent.mkdir(exist_ok=True)
        marker_tmp = marker.with_suffix(".tmp")
        marker_tmp.write_text(
            json.dumps(
                {"version": info.version, "staging": str(staging), "restart_required": True}
            ),
            encoding="utf-8",
        )
        os.replace(marker_tmp, marker)
        return UpdateResult(True, "更新已下載，將在重新啟動時套用。", info.version, True)
    except Exception as error:
        if staging_container is not None and staging_container.exists():
            import shutil

            shutil.rmtree(staging_container, ignore_errors=True)
        if marker_tmp is not None:
            marker_tmp.unlink(missing_ok=True)
        return UpdateResult(False, f"下載更新失敗：{error}", info.version)
    finally:
        if own:
            await http.aclose()


class UpdateWatcher:
    def __init__(
        self,
        state_store: StateStore,
        check_interval_seconds: float = 1800.0,
        on_change: Callable[[UpdateInfo | None], Awaitable[None]] | None = None,
    ) -> None:
        self._state, self._interval, self._on_change = (
            state_store,
            check_interval_seconds,
            on_change,
        )
        self._task = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(10)
        while True:
            try:
                info = await check_for_update()
                await self._state.update(
                    update_available=info.version if info and info.available else None
                )
                if self._on_change:
                    await self._on_change(info)
            except Exception:
                pass
            await asyncio.sleep(self._interval)
