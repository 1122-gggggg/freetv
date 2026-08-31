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
from typing import Literal

import httpx

from app.config import project_root
from app.logging import log_event
from app.state import StateStore

logger = logging.getLogger(__name__)
GITHUB_REPO = "1122-gggggg/freetv"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_INSTALLER_BYTES = 250 * 1024 * 1024
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
    artifact_kind: Literal["archive", "installer"] = "archive"
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


async def check_for_update(
    root: Path | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> UpdateInfo | None:
    base = root or project_root()
    installer_mode = (
        (base / "runtime" / "python.exe").is_file()
        and not (base / "runtime" / "python.exe").is_symlink()
    )
    artifact_kind: Literal["archive", "installer"] = (
        "installer" if installer_mode else "archive"
    )
    artifact_name = "FreeTV-Setup.exe" if installer_mode else "pc-tv-box.zip"
    checksum_name = f"{artifact_name}.sha256"
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
                "FreeTV-Setup.exe",
                "FreeTV-Setup.exe.sha256",
            ):
                found[asset["name"]] = str(asset.get("browser_download_url") or "")
        if (
            tag
            and parse_version(tag) > parse_version(CURRENT_VERSION)
            and all(found.get(name) for name in (artifact_name, checksum_name))
        ):
            _require_trusted_update_url(found[artifact_name])
            _require_trusted_update_url(found[checksum_name])
            return UpdateInfo(
                available=True,
                version=tag,
                release_name=str(payload.get("name") or tag),
                release_notes=str(payload.get("body") or "")[:500],
                artifact_kind=artifact_kind,
                download_url=found[artifact_name],
                checksum_url=found[checksum_name],
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


async def _download_file_limited(
    client: httpx.AsyncClient,
    url: str,
    destination: Path,
    *,
    maximum_bytes: int,
) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    _require_trusted_update_url(url)
    async with client.stream("GET", url, follow_redirects=True) as response:
        for redirect in response.history:
            _require_trusted_update_url(str(redirect.url))
        _require_trusted_update_url(str(response.url))
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError as error:
                raise ValueError("更新下載資訊無效") from error
            if declared_size < 0 or declared_size > maximum_bytes:
                raise ValueError("更新檔過大")
        with destination.open("wb", buffering=0) as output:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > maximum_bytes:
                    raise ValueError("更新檔過大")
                digest.update(chunk)
                output.write(chunk)
    return size, digest.hexdigest()



def _prior_installer_source(
    marker: Path, updates: Path
) -> tuple[Path, os.stat_result] | None:
    try:
        if marker.is_symlink() or not marker.is_file():
            return None
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if not str(payload["version"]).strip():
            return None
        expected_digest = str(payload["sha256"]).strip()
        if (
            len(expected_digest) != 64
            or any(
                character not in "0123456789abcdefABCDEF"
                for character in expected_digest
            )
        ):
            return None
        source = Path(str(payload["installer"])).expanduser()
        source = source if source.is_absolute() else marker.parent / source
        source.resolve().relative_to(updates.resolve())
        source_stat = source.stat(follow_symlinks=False)
        if (
            source.is_symlink()
            or not stat.S_ISREG(source_stat.st_mode)
            or source_stat.st_size <= 0
            or source_stat.st_size > MAX_INSTALLER_BYTES
        ):
            return None
        digest = hashlib.sha256()
        with source.open("rb") as input_file:
            while chunk := input_file.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest().lower() != expected_digest.lower():
            return None
        return source, source_stat
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _unlink_best_effort(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

async def apply_update(
    root: Path | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    info: UpdateInfo | None = None,
) -> UpdateResult:
    base = root or project_root()
    info = info or await check_for_update(base, client=client)
    if not info or not info.download_url or not info.checksum_url:
        return UpdateResult(False, "找不到可用的正式版本更新。")
    own = client is None
    http = client or httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    staging_container: Path | None = None
    installer_temporary: Path | None = None
    installer_destination: Path | None = None
    marker_tmp: Path | None = None
    prior_installer: tuple[Path, os.stat_result] | None = None
    try:
        parent = base / "config" / "updates"
        if (base / "config").is_symlink() or parent.is_symlink():
            raise ValueError("更新暫存目錄不安全")
        parent.mkdir(parents=True, exist_ok=True)
        safe_version = (
            "".join(c if c.isalnum() or c in ".-_" else "_" for c in info.version)[:80]
            or "update"
        )
        if info.artifact_kind == "installer":
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f"FreeTV-Setup-{safe_version}-",
                suffix=".tmp",
                dir=parent,
            )
            os.close(descriptor)
            installer_temporary = Path(temporary_name)
            size, digest = await _download_file_limited(
                http,
                info.download_url,
                installer_temporary,
                maximum_bytes=MAX_INSTALLER_BYTES,
            )
            checksum_payload = await _download_limited(
                http,
                info.checksum_url,
                maximum_bytes=4_096,
            )
            checksum = checksum_payload.decode("ascii", errors="strict").strip().split()[0]
            if (
                size == 0
                or len(checksum) != 64
                or digest.lower() != checksum.lower()
            ):
                raise ValueError("更新檔校驗失敗")
            installer_destination = installer_temporary.with_suffix(".exe")
            os.replace(installer_temporary, installer_destination)
            installer_temporary = None
            marker = parent / "pending-installer-update.json"
            prior_installer = _prior_installer_source(marker, parent)
            descriptor, marker_name = tempfile.mkstemp(
                prefix=".pending-installer-update-",
                suffix=".tmp",
                dir=parent,
            )
            marker_tmp = Path(marker_name)
            marker_payload = {
                "version": info.version,
                "installer": str(installer_destination),
                "sha256": digest,
            }
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    json.dump(marker_payload, output)
            except Exception:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
            marker_stat = marker_tmp.stat(follow_symlinks=False)
            if marker_tmp.is_symlink() or not stat.S_ISREG(marker_stat.st_mode):
                raise ValueError("更新標記檔不安全")
            os.replace(marker_tmp, marker)
            marker_tmp = None
            if prior_installer is not None:
                prior_source, prior_stat = prior_installer
                try:
                    unchanged = os.path.samestat(
                        prior_stat, prior_source.stat(follow_symlinks=False)
                    )
                    if (
                        unchanged
                        and not prior_source.is_symlink()
                        and prior_source.resolve() != installer_destination.resolve()
                    ):
                        prior_source.unlink()
                except OSError:
                    pass
            installer_destination = None
            return UpdateResult(
                True,
                "更新已下載，將在重新啟動時執行安裝程式。",
                info.version,
                True,
            )
        if info.artifact_kind != "archive":
            raise ValueError("更新檔類型無效")
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
        marker_tmp = None
        return UpdateResult(True, "更新已下載，將在重新啟動時套用。", info.version, True)
    except Exception as error:
        if staging_container is not None and staging_container.exists():
            import shutil

            shutil.rmtree(staging_container, ignore_errors=True)
        _unlink_best_effort(installer_temporary)
        _unlink_best_effort(installer_destination)
        _unlink_best_effort(marker_tmp)
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
