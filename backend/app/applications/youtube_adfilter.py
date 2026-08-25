from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any

import httpx
import websockets

from app.logging import log_event

logger = logging.getLogger(__name__)

BLOCKED_URL_PATTERNS: tuple[str, ...] = (
    "*://*.doubleclick.net/*",
    "*://*.googleadservices.com/*",
    "*://*.googlesyndication.com/*",
    "*://*.googleads.g.doubleclick.net/*",
    "*://*.adservice.google.com/*",
    "*://*.adservice.google.com.tw/*",
    "*://*.adtrafficquality.google/*",
    "*://*.2mdn.net/*",
    "*://*.adsafeprotected.com/*",
    "*://www.youtube.com/pagead/*",
    "*://www.youtube.com/ptracking*",
    "*://www.youtube.com/api/stats/ads*",
    "*://www.youtube.com/get_midroll_*",
    "*://youtube.com/pagead/*",
    "*://youtube.com/ptracking*",
    "*://youtube.com/api/stats/ads*",
)

SKIP_ADS_SCRIPT = """(() => {
  if (window.__pcTvAdFilter) return;
  window.__pcTvAdFilter = 1;
  const clickSelectors = [
    ".ytp-ad-skip-button",
    ".ytp-ad-skip-button-modern",
    ".ytp-skip-ad-button",
    ".ytp-ad-skip-button-container button",
    ".ytp-ad-overlay-close-button"
  ];
  const hideSelectors = [
    ".ytp-ad-overlay-container",
    ".ytp-ad-player-overlay",
    "#player-ads",
    "ytd-ad-slot-renderer",
    "ytd-promoted-sparkles-web-renderer",
    "ytd-in-feed-ad-layout-renderer"
  ];
  const tick = () => {
    for (const selector of clickSelectors) {
      const node = document.querySelector(selector);
      if (node instanceof HTMLElement) node.click();
    }
    for (const selector of hideSelectors) {
      document.querySelectorAll(selector).forEach((node) => {
        if (node instanceof HTMLElement) node.style.setProperty("display", "none", "important");
      });
    }
    const video = document.querySelector("video");
    const ad = document.querySelector(".ad-showing");
    if (video instanceof HTMLVideoElement && ad) {
      video.muted = true;
      video.playbackRate = 16;
    } else if (video instanceof HTMLVideoElement && video.playbackRate === 16) {
      video.playbackRate = 1;
    }
  };
  setInterval(tick, 400);
  new MutationObserver(tick).observe(document.documentElement, {childList: true, subtree: true});
  tick();
})();"""


def reserve_localhost_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class YoutubeAdFilter:
    def __init__(self, timeout: float = 8.0) -> None:
        self._timeout = timeout

    async def attach(self, port: int) -> None:
        pages = await self._wait_for_pages(port)
        for page in pages:
            debugger = page.get("webSocketDebuggerUrl")
            if not debugger:
                continue
            await self._configure_page(str(debugger))
        log_event(logger, "youtube_adfilter_attached", port=port, pages=len(pages))

    async def _wait_for_pages(self, port: int) -> list[dict[str, Any]]:
        deadline = asyncio.get_running_loop().time() + self._timeout
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:
                    response = await client.get(f"http://127.0.0.1:{port}/json/list")
                    response.raise_for_status()
                    pages = [
                        page
                        for page in response.json()
                        if page.get("type") == "page" and page.get("webSocketDebuggerUrl")
                    ]
                    if pages:
                        return pages
            except Exception as error:  # noqa: BLE001 - retry until timeout
                last_error = error
            await asyncio.sleep(0.2)
        raise RuntimeError(f"Chrome debugger pages were not ready on 127.0.0.1:{port}: {last_error}")

    async def _configure_page(self, debugger_url: str) -> None:
        async with websockets.connect(debugger_url, open_timeout=self._timeout, max_size=2**22) as socket:
            await self._call(socket, 1, "Network.enable", {})
            await self._call(
                socket,
                2,
                "Network.setBlockedURLs",
                {"urls": list(BLOCKED_URL_PATTERNS)},
            )
            await self._call(
                socket,
                3,
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": SKIP_ADS_SCRIPT},
            )
            await self._call(socket, 4, "Runtime.evaluate", {"expression": SKIP_ADS_SCRIPT})

    @staticmethod
    async def _call(socket: Any, command_id: int, method: str, params: dict[str, Any]) -> None:
        await socket.send(json.dumps({"id": command_id, "method": method, "params": params}))
        await socket.recv()
