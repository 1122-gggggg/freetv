from __future__ import annotations

import asyncio
import logging
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import project_root
from app.logging import log_event
from app.state import StateStore

logger = logging.getLogger(__name__)

CURRENT_VERSION = "0.2.0"
GITHUB_REPO = "1122-gggggg/freetv"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_COMMITS_URL = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    available: bool
    version: str
    release_name: str
    release_notes: str
    download_url: str | None = None


def get_current_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root(),
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout.strip()
    except Exception:
        pass
    return None


async def check_for_update(*, client: httpx.AsyncClient | None = None) -> UpdateInfo | None:
    headers = {"User-Agent": "FreeTV-Appliance"}
    should_close = False
    http = client
    if http is None:
        http = httpx.AsyncClient(timeout=8.0, headers=headers)
        should_close = True
    try:
        # First try GitHub Releases API
        response = await http.get(GITHUB_API_URL)
        if response.status_code == 200:
            payload = response.json()
            if isinstance(payload, dict):
                tag_name = str(payload.get("tag_name") or payload.get("name") or "").strip()
                body = str(payload.get("body") or "").strip()
                assets = payload.get("assets", [])
                zip_url = None
                if isinstance(assets, list):
                    for asset in assets:
                        if isinstance(asset, dict) and str(asset.get("name", "")).endswith(".zip"):
                            zip_url = str(asset.get("browser_download_url") or "")
                            break
                if tag_name and tag_name != CURRENT_VERSION and tag_name != f"v{CURRENT_VERSION}":
                    return UpdateInfo(
                        available=True,
                        version=tag_name,
                        release_name=str(payload.get("name") or tag_name),
                        release_notes=body[:500],
                        download_url=zip_url,
                    )

        # Fallback to checking latest commit on main branch
        commit_res = await http.get(GITHUB_COMMITS_URL)
        if commit_res.status_code == 200:
            commit_payload = commit_res.json()
            if isinstance(commit_payload, dict):
                remote_sha = str(commit_payload.get("sha") or "")[:7]
                local_sha = get_current_commit()
                message = str(commit_payload.get("commit", {}).get("message") or "").split("\n")[0]
                if remote_sha and local_sha and remote_sha != local_sha:
                    return UpdateInfo(
                        available=True,
                        version=remote_sha,
                        release_name=f"Commit {remote_sha}",
                        release_notes=message[:200],
                        download_url=None,
                    )
        return None
    except Exception as error:
        log_event(logger, "update_check_failed", error=str(error))
        return None
    finally:
        if should_close:
            await http.aclose()


def apply_git_update(root: Path | None = None) -> bool:
    base = root or project_root()
    try:
        fetch = subprocess.run(
            ["git", "pull", "--rebase", "origin", "main"],
            cwd=base,
            capture_output=True,
            text=True,
            check=False,
            timeout=30.0,
        )
        if fetch.returncode == 0:
            return True
    except Exception:
        pass
    return False


async def apply_update(root: Path | None = None) -> tuple[bool, str]:
    base = root or project_root()
    log_event(logger, "update_apply_started")
    git_dir = base / ".git"
    if git_dir.exists():
        success = await asyncio.to_thread(apply_git_update, base)
        if success:
            log_event(logger, "update_applied_git")
            return True, "更新已成功下載並套用。"

    # Fallback to downloading release zip
    info = await check_for_update()
    if info and info.download_url:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(info.download_url)
                if res.status_code == 200:
                    zip_path = base / "update.zip"
                    zip_path.write_bytes(res.content)
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        zf.extractall(base)
                    zip_path.unlink(missing_ok=True)
                    log_event(logger, "update_applied_zip")
                    return True, "更新壓縮檔已成功套用。"
        except Exception as error:
            return False, f"下載更新失敗：{error}"

    return False, "無法套用更新，請檢查網路連線或使用 git 更新。"


class UpdateWatcher:
    def __init__(self, state_store: StateStore, check_interval_seconds: float = 1800.0) -> None:
        self._state = state_store
        self._interval = check_interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        # Initial check after 10s
        await asyncio.sleep(10.0)
        while True:
            try:
                info = await check_for_update()
                if info and info.available:
                    await self._state.update(update_available=info.version)
                else:
                    await self._state.update(update_available=None)
            except Exception:
                pass
            await asyncio.sleep(self._interval)
