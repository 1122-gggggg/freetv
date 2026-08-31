from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Protocol, TypedDict
from urllib.parse import parse_qs, urlparse

import httpx
import websockets

from app.applications.playback_rate import PLAYBACK_RATE_STEPS
from app.commands.ports import CommandExecutionError


class YoutubeQualityInfo(TypedDict):
    video_id: str
    current: str
    available: list[str]


_QUALITY_RANK = {
    "auto": -1,
    "tiny": 0,
    "small": 1,
    "medium": 2,
    "large": 3,
    "hd720": 4,
    "hd1080": 5,
    "hd1440": 6,
    "hd2160": 7,
    "highres": 8,
}
_QUALITY_CODE = re.compile(r"^[a-z0-9_-]{1,32}$")

_INSPECT_EXPRESSION = """(() => {
  const video = document.querySelector('video');
  return {
    url: location.href,
    ready: video?.readyState >= 2,
    fullscreen: document.fullscreenElement !== null,
  };
})()"""


def _fullscreen_expression(video_id: str = "") -> str:
    expected = json.dumps(video_id, ensure_ascii=True)
    return f"""(async () => {{
  const expected = {expected};
  const getIdentity = () => {{
    const url = new URL(location.href);
    const youtubeHost =
      url.hostname === 'youtube.com' || url.hostname.endsWith('.youtube.com');
    if (!youtubeHost) return null;
    const queryId = url.searchParams.get('v');
    if ((url.pathname.endsWith('/watch') || url.pathname.includes('/watch')) && queryId) {{
      return `watch:${{queryId}}`;
    }}
    if (url.hash.startsWith('#/watch?')) {{
      const params = new URLSearchParams(url.hash.split('?')[1] || '');
      if (params.get('v')) return `watch:${{params.get('v')}}`;
    }}
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length >= 2 && ['shorts', 'live'].includes(parts[parts.length - 2])) {{
      return `${{parts[parts.length - 2]}}:${{parts[parts.length - 1]}}`;
    }}
    if (parts.length >= 2 && parts[parts.length - 1] === 'live') {{
      return `live:${{parts[parts.length - 2]}}`;
    }}
    if (parts.length >= 1 && parts[parts.length - 1] === 'live') {{
      return 'live:default';
    }}
    if (url.pathname.startsWith('/live/')) {{
      return `live:${{url.pathname.slice(6)}}`;
    }}
    if (url.pathname.startsWith('/shorts/')) {{
      return `shorts:${{url.pathname.slice(8)}}`;
    }}
    return null;
  }};
  if (expected) {{
    const identity = getIdentity();
    if (identity && identity !== expected) return false;
  }}
  const video = [...document.querySelectorAll('video')].find(
    (element) => element instanceof HTMLVideoElement && element.readyState >= 2
  ) || document.querySelector('video');
  if (!video) return false;

  if (document.fullscreenElement !== null) {{
    if (typeof document.exitFullscreen === 'function') {{
      try {{
        await document.exitFullscreen();
        return true;
      }} catch {{}}
    }}
  }}

  const target = (
    document.querySelector('#movie_player') ||
    document.querySelector('.html5-video-player') ||
    video
  );
  const request = (
    target.requestFullscreen ||
    target.webkitRequestFullscreen ||
    video.webkitRequestFullscreen
  );
  if (typeof request === 'function') {{
    try {{
      await request.call(target);
      return true;
    }} catch {{}}
  }}
  return false;
}})()"""


def _show_osd_expression(text: str) -> str:
    escaped_text = json.dumps(text, ensure_ascii=True)
    return f"""(() => {{
  try {{
    const id = '__freetv_osd__';
    let osd = document.getElementById(id);
    if (!osd) {{
      osd = document.createElement('div');
      osd.id = id;
      osd.style.cssText = [
        'position: fixed',
        'top: 48px',
        'right: 48px',
        'z-index: 2147483647',
        'background: rgba(0, 0, 0, 0.84)',
        'color: #ffffff',
        'font-size: 32px',
        'font-weight: 700',
        'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        'padding: 16px 32px',
        'border-radius: 16px',
        'box-shadow: 0 8px 32px rgba(0,0,0,0.6)',
        'pointer-events: none',
        'transition: opacity 0.25s ease',
        'opacity: 0',
        'backdrop-filter: blur(12px)',
        'display: flex',
        'align-items: center',
        'gap: 12px',
        'border: 1px solid rgba(255, 255, 255, 0.22)',
      ].join(';');
    }}
    osd.textContent = {escaped_text};
    const host = (document.fullscreenElement && document.fullscreenElement.tagName !== 'VIDEO')
      ? document.fullscreenElement
      : (document.body || document.documentElement);
    if (osd.parentElement !== host) {{
      host.appendChild(osd);
    }}
    requestAnimationFrame(() => {{
      osd.style.opacity = '1';
    }});
    clearTimeout(window.__freetv_osd_timer__);
    window.__freetv_osd_timer__ = setTimeout(() => {{
      osd.style.opacity = '0';
      setTimeout(() => {{
        if (osd.parentElement && osd.style.opacity === '0') {{
          osd.remove();
        }}
      }}, 300);
    }}, 1800);
    return true;
  }} catch {{
    return false;
  }}
}})()"""


def _rate_expression(direction: int) -> str:
    steps = json.dumps(list(PLAYBACK_RATE_STEPS), ensure_ascii=True)
    step = 1 if direction > 0 else -1
    return f"""(() => {{
  const steps = {steps};
  const video = [...document.querySelectorAll('video')].find(
    (element) => element instanceof HTMLVideoElement && element.readyState >= 2
  );
  if (!video) return null;
  const current = Number(video.playbackRate) || 1;
  let index = steps.findIndex((rate) => Math.abs(rate - current) < 0.01);
  if (index < 0) index = steps.indexOf(1);
  const next = steps[Math.max(0, Math.min(steps.length - 1, index + {step}))];
  video.playbackRate = next;
  const formatted = `${next}`.replace(/\\.0$/, '');
  try {{
    const id = '__freetv_osd__';
    let osd = document.getElementById(id);
    if (!osd) {{
      osd = document.createElement('div');
      osd.id = id;
      osd.style.cssText = [
        'position: fixed',
        'top: 48px',
        'right: 48px',
        'z-index: 2147483647',
        'background: rgba(0, 0, 0, 0.84)',
        'color: #ffffff',
        'font-size: 32px',
        'font-weight: 700',
        'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        'padding: 16px 32px',
        'border-radius: 16px',
        'box-shadow: 0 8px 32px rgba(0,0,0,0.6)',
        'pointer-events: none',
        'transition: opacity 0.25s ease',
        'opacity: 0',
        'backdrop-filter: blur(12px)',
        'display: flex',
        'align-items: center',
        'gap: 12px',
        'border: 1px solid rgba(255, 255, 255, 0.22)',
      ].join(';');
    }}
    osd.textContent = `倍速 ${{formatted}}×`;
    const host = (document.fullscreenElement && document.fullscreenElement.tagName !== 'VIDEO')
      ? document.fullscreenElement
      : (document.body || document.documentElement);
    if (osd.parentElement !== host) {{
      host.appendChild(osd);
    }}
    requestAnimationFrame(() => {{
      osd.style.opacity = '1';
    }});
    clearTimeout(window.__freetv_osd_timer__);
    window.__freetv_osd_timer__ = setTimeout(() => {{
      osd.style.opacity = '0';
      setTimeout(() => {{
        if (osd.parentElement && osd.style.opacity === '0') {{
          osd.remove();
        }}
      }}, 300);
    }}, 1800);
  }} catch {{}}
  return next;
}})()"""


def _seek_expression(direction: int) -> str:
    seconds = 5 if direction > 0 else -5
    return f"""(() => {{
  const video = [...document.querySelectorAll('video')].find(
    (element) => element instanceof HTMLVideoElement && element.readyState >= 2
  );
  if (!video) return false;
  const duration = Number(video.duration);
  const target = Math.max(
    0,
    Number.isFinite(duration)
      ? Math.min(duration, video.currentTime + {seconds})
      : video.currentTime + {seconds}
  );
  video.currentTime = target;
  return true;
}})()"""


def _quality_info_expression() -> str:
    return """(() => {
  const player =
    document.querySelector('#movie_player') ||
    document.querySelector('.html5-video-player');
  if (!player || typeof player.getAvailableQualityLevels !== 'function') return null;
  try {
    const levels = player.getAvailableQualityLevels();
    const current = typeof player.getPlaybackQuality === 'function'
      ? player.getPlaybackQuality()
      : '';
    const videoData = typeof player.getVideoData === 'function' ? player.getVideoData() : null;
    const urlVideoId = new URL(location.href).searchParams.get('v') || '';
    const videoId = typeof videoData?.video_id === 'string' && videoData.video_id
      ? videoData.video_id
      : urlVideoId;
    if (!videoId || !Array.isArray(levels) || levels.length === 0) return null;
    return {
      video_id: videoId,
      current,
      available: [...new Set(levels)],
    };
  } catch {
    return null;
  }
})()"""


def _set_quality_expression(quality: str) -> str:
    requested = json.dumps(quality, ensure_ascii=True)
    return f"""(() => {{
  const requested = {requested};
  const player =
    document.querySelector('#movie_player') ||
    document.querySelector('.html5-video-player');
  if (!player || typeof player.getAvailableQualityLevels !== 'function') return null;
  try {{
    const levels = player.getAvailableQualityLevels();
    if (!Array.isArray(levels) || !levels.includes(requested)) return null;
    if (typeof player.setPlaybackQualityRange === 'function') {{
      player.setPlaybackQualityRange(requested, requested);
    }}
    if (typeof player.setPlaybackQuality === 'function') {{
      player.setPlaybackQuality(requested);
    }}
    const videoData = typeof player.getVideoData === 'function' ? player.getVideoData() : null;
    const urlVideoId = new URL(location.href).searchParams.get('v') || '';
    const videoId = typeof videoData?.video_id === 'string' && videoData.video_id
      ? videoData.video_id
      : urlVideoId;
    if (!videoId) return null;
    return {{
      video_id: videoId,
      current: requested,
      available: [...new Set(levels)],
    }};
  }} catch {{
    return null;
  }}
}})()"""


def _quality_info(value: Any) -> YoutubeQualityInfo:
    if not isinstance(value, dict) or set(value) != {"video_id", "current", "available"}:
        raise ValueError("YouTube quality result must contain the expected fields")
    video_id = value["video_id"]
    current = value["current"]
    available = value["available"]
    if (
        not isinstance(video_id, str)
        or not 1 <= len(video_id) <= 128
        or not isinstance(current, str)
        or _QUALITY_CODE.fullmatch(current) is None
        or not isinstance(available, list)
        or not 1 <= len(available) <= 20
        or any(
            not isinstance(level, str) or _QUALITY_CODE.fullmatch(level) is None
            for level in available
        )
    ):
        raise ValueError("YouTube quality result is invalid")
    levels = set(available)
    ordered = sorted(
        levels,
        key=lambda level: (_QUALITY_RANK.get(level, len(_QUALITY_RANK)), level),
    )
    return {"video_id": video_id, "current": current, "available": ordered}


def _quality_expression() -> str:
    return """(() => {
  const player =
    document.querySelector('#movie_player') ||
    document.querySelector('.html5-video-player');
  const labels = {
    'highres': '4K 最高畫質',
    'hd2160': '4K (2160p)',
    'hd1440': '2K (1440p)',
    'hd1080': '1080p 高畫質',
    'hd720': '720p',
    'large': '480p',
    'medium': '360p',
    'small': '240p',
    'tiny': '144p',
    'auto': '自動 (最佳)',
  };
  let resultLabel = '自動';
  if (player && typeof player.getAvailableQualityLevels === 'function') {
    try {
      const levels = player.getAvailableQualityLevels();
      const current = player.getPlaybackQuality ? player.getPlaybackQuality() : 'auto';
      if (Array.isArray(levels) && levels.length > 0) {
        let index = levels.indexOf(current);
        let next = levels[(index + 1) % levels.length];
        if (typeof player.setPlaybackQualityRange === 'function') {
          player.setPlaybackQualityRange(next, next);
        }
        if (typeof player.setPlaybackQuality === 'function') {
          player.setPlaybackQuality(next);
        }
        resultLabel = labels[next] || next;
      }
    } catch {}
  }
  try {
    const id = '__freetv_osd__';
    let osd = document.getElementById(id);
    if (!osd) {
      osd = document.createElement('div');
      osd.id = id;
      osd.style.cssText = [
        'position: fixed',
        'top: 48px',
        'right: 48px',
        'z-index: 2147483647',
        'background: rgba(0, 0, 0, 0.84)',
        'color: #ffffff',
        'font-size: 32px',
        'font-weight: 700',
        'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        'padding: 16px 32px',
        'border-radius: 16px',
        'box-shadow: 0 8px 32px rgba(0,0,0,0.6)',
        'pointer-events: none',
        'transition: opacity 0.25s ease',
        'opacity: 0',
        'backdrop-filter: blur(12px)',
        'display: flex',
        'align-items: center',
        'gap: 12px',
        'border: 1px solid rgba(255, 255, 255, 0.22)',
      ].join(';');
    }
    osd.textContent = `畫質 ${resultLabel}`;
    const host = (document.fullscreenElement && document.fullscreenElement.tagName !== 'VIDEO')
      ? document.fullscreenElement
      : (document.body || document.documentElement);
    if (osd.parentElement !== host) {
      host.appendChild(osd);
    }
    requestAnimationFrame(() => {
      osd.style.opacity = '1';
    });
    clearTimeout(window.__freetv_osd_timer__);
    window.__freetv_osd_timer__ = setTimeout(() => {
      osd.style.opacity = '0';
      setTimeout(() => {
        if (osd.parentElement && osd.style.opacity === '0') {
          osd.remove();
        }
      }, 300);
    }, 1800);
  } catch {}
  return resultLabel;
})()"""


def _subtitles_expression() -> str:
    return """(() => {
  const player =
    document.querySelector('#movie_player') ||
    document.querySelector('.html5-video-player');
  let result = '切換';
  if (player && typeof player.toggleSubtitles === 'function') {
    try {
      player.toggleSubtitles();
      result = '已切換';
    } catch {}
  }
  try {
    const id = '__freetv_osd__';
    let osd = document.getElementById(id);
    if (!osd) {
      osd = document.createElement('div');
      osd.id = id;
      osd.style.cssText = [
        'position: fixed',
        'top: 48px',
        'right: 48px',
        'z-index: 2147483647',
        'background: rgba(0, 0, 0, 0.84)',
        'color: #ffffff',
        'font-size: 32px',
        'font-weight: 700',
        'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        'padding: 16px 32px',
        'border-radius: 16px',
        'box-shadow: 0 8px 32px rgba(0,0,0,0.6)',
        'pointer-events: none',
        'transition: opacity 0.25s ease',
        'opacity: 0',
        'backdrop-filter: blur(12px)',
        'display: flex',
        'align-items: center',
        'gap: 12px',
        'border: 1px solid rgba(255, 255, 255, 0.22)',
      ].join(';');
    }
    osd.textContent = `字幕 ${result}`;
    const host = (document.fullscreenElement && document.fullscreenElement.tagName !== 'VIDEO')
      ? document.fullscreenElement
      : (document.body || document.documentElement);
    if (osd.parentElement !== host) {
      host.appendChild(osd);
    }
    requestAnimationFrame(() => {
      osd.style.opacity = '1';
    });
    clearTimeout(window.__freetv_osd_timer__);
    window.__freetv_osd_timer__ = setTimeout(() => {
      osd.style.opacity = '0';
      setTimeout(() => {
        if (osd.parentElement && osd.style.opacity === '0') {
          osd.remove();
        }
      }, 300);
    }, 1800);
  } catch {}
  return result;
})()"""
class YoutubeProbe(Protocol):
    async def inspect(self, port: int) -> tuple[str | None, bool, bool]: ...
    async def fullscreen(self, port: int, video_id: str, user_gesture: bool) -> bool: ...
    async def playback_rate(self, port: int, direction: int) -> float: ...
    async def seek(self, port: int, direction: int) -> bool: ...
    async def quality_info(self, port: int) -> YoutubeQualityInfo: ...
    async def set_quality(self, port: int, quality: str) -> YoutubeQualityInfo: ...
    async def cycle_quality(self, port: int) -> str: ...
    async def toggle_subtitles(self, port: int) -> str: ...
    async def show_osd(self, port: int, text: str) -> bool: ...

def extract_video_identity(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host != "youtube.com" and not host.endswith(".youtube.com"):
        return None
    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if (parsed.path.endswith("/watch") or "/watch" in parsed.path) and query_id:
        return f"watch:{query_id}"

    if parsed.fragment.startswith("/watch?"):
        hash_id = parse_qs(parsed.fragment.partition("?")[2]).get("v", [None])[0]
        if hash_id:
            return f"watch:{hash_id}"

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[-2] in {"shorts", "live"}:
        return f"{parts[-2]}:{parts[-1]}"
    if len(parts) >= 2 and parts[-1] == "live":
        return f"live:{parts[-2]}"
    if len(parts) >= 1 and parts[-1] == "live":
        return "live:default"
    if parsed.path.startswith("/live/"):
        return f"live:{parsed.path[6:]}"
    if parsed.path.startswith("/shorts/"):
        return f"shorts:{parsed.path[8:]}"
    return None


class ShortCdpYoutubeProbe:
    def __init__(self, timeout: float = 0.8) -> None:
        self._timeout = timeout
        self._command_id = 0

    async def inspect(self, port: int) -> tuple[str | None, bool, bool]:
        debugger_url = await self._debugger_url(port)
        value = await self._evaluate(debugger_url, _INSPECT_EXPRESSION)
        if not isinstance(value, dict):
            raise ValueError("YouTube inspection result must be an object")
        url = value.get("url")
        ready = value.get("ready")
        fullscreen = value.get("fullscreen")
        if not isinstance(url, str) or type(ready) is not bool or type(fullscreen) is not bool:
            raise ValueError("YouTube inspection result is invalid")
        return extract_video_identity(url), ready, fullscreen

    async def fullscreen(self, port: int, video_id: str = "", user_gesture: bool = True) -> bool:
        if user_gesture is not True:
            raise ValueError("A user gesture is required")
        debugger_url = await self._debugger_url(port)
        value = await self._evaluate(
            debugger_url,
            _fullscreen_expression(video_id),
            user_gesture=True,
        )
        if type(value) is not bool:
            raise ValueError("YouTube fullscreen result is invalid")
        return value

    async def show_osd(self, port: int, text: str) -> bool:
        debugger_url = await self._debugger_url(port)
        value = await self._evaluate(
            debugger_url,
            _show_osd_expression(text),
            user_gesture=True,
        )
        return bool(value)

    async def playback_rate(self, port: int, direction: int) -> float:
        if direction not in {1, -1}:
            raise ValueError("direction must be 1 or -1")
        debugger_url = await self._debugger_url(port)
        value = await self._evaluate(
            debugger_url,
            _rate_expression(direction),
            user_gesture=True,
        )
        if type(value) not in {int, float}:
            raise ValueError("YouTube playback rate result is invalid")
        return float(value)

    async def seek(self, port: int, direction: int) -> bool:
        if direction not in {1, -1}:
            raise ValueError("direction must be 1 or -1")
        debugger_url = await self._debugger_url(port)
        value = await self._evaluate(
            debugger_url,
            _seek_expression(direction),
            user_gesture=True,
        )
        if type(value) is not bool:
            raise ValueError("YouTube seek result is invalid")
        return value

    async def quality_info(self, port: int) -> YoutubeQualityInfo:
        debugger_url = await self._debugger_url(port)
        value = await self._evaluate(debugger_url, _quality_info_expression())
        return _quality_info(value)

    async def set_quality(self, port: int, quality: str) -> YoutubeQualityInfo:
        if not isinstance(quality, str) or _QUALITY_CODE.fullmatch(quality) is None:
            raise ValueError("YouTube quality code is invalid")
        debugger_url = await self._debugger_url(port)
        value = await self._evaluate(
            debugger_url,
            _set_quality_expression(quality),
            user_gesture=True,
        )
        return _quality_info(value)

    async def cycle_quality(self, port: int) -> str:
        debugger_url = await self._debugger_url(port)
        value = await self._evaluate(debugger_url, _quality_expression(), user_gesture=True)
        return str(value or "自動")

    async def toggle_subtitles(self, port: int) -> str:
        debugger_url = await self._debugger_url(port)
        value = await self._evaluate(debugger_url, _subtitles_expression(), user_gesture=True)
        return str(value or "已切換")
    async def _debugger_url(self, port: int) -> str:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("CDP port is invalid")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(f"http://127.0.0.1:{port}/json/list")
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("CDP target list must be an array")

        targets = [
            page
            for page in payload
            if isinstance(page, dict)
            and page.get("type") == "page"
            and not page.get("openerId")
            and _is_youtube_url(page.get("url"))
        ]
        if len(targets) != 1:
            raise ValueError("A unique top-level YouTube target is required")
        debugger_url = targets[0].get("webSocketDebuggerUrl")
        if not _is_local_debugger_url(debugger_url, port):
            raise ValueError("YouTube debugger target must be local")
        return debugger_url

    async def _evaluate(
        self,
        debugger_url: str,
        expression: str,
        *,
        user_gesture: bool = False,
    ) -> Any:
        self._command_id += 1
        command_id = self._command_id
        params: dict[str, Any] = {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        }
        if user_gesture:
            params["userGesture"] = True
        request = json.dumps(
            {"id": command_id, "method": "Runtime.evaluate", "params": params},
            ensure_ascii=True,
        )

        async with websockets.connect(
            debugger_url,
            open_timeout=self._timeout,
            max_size=2**20,
        ) as socket:
            await asyncio.wait_for(socket.send(request), timeout=self._timeout)
            while True:
                raw = await asyncio.wait_for(socket.recv(), timeout=self._timeout)
                if not isinstance(raw, str):
                    raise ValueError("CDP response must be text")
                payload = json.loads(raw)
                if not isinstance(payload, dict) or payload.get("id") != command_id:
                    continue
                if payload.get("error") is not None:
                    raise ValueError("CDP Runtime.evaluate failed")
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise ValueError("CDP Runtime.evaluate result is invalid")
                if result.get("exceptionDetails") is not None:
                    raise ValueError("CDP Runtime.evaluate value is invalid")
                remote = result.get("result")
                if not isinstance(remote, dict):
                    raise ValueError("CDP Runtime.evaluate value is invalid")
                return remote.get("value")


class YoutubeFullscreenController:
    def __init__(
        self,
        interval_seconds: float = 1.0,
        timeout: float = 0.8,
        *,
        probe: YoutubeProbe | None = None,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._probe = probe or ShortCdpYoutubeProbe(timeout)
        self._task: asyncio.Task[None] | None = None
        self._port: int | None = None
        self._last_fullscreen_video_id: str | None = None
        self._last_quality_video_id: str | None = None
        self._probe_lock = asyncio.Lock()

    async def start(self, port: int) -> None:
        if self._task is not None and not self._task.done() and self._port == port:
            return
        await self.stop()
        self._port = port
        self._last_fullscreen_video_id = None
        self._last_quality_video_id = None
        self._task = asyncio.create_task(self._run(port))

    async def stop(self) -> None:
        task, self._task = self._task, None
        self._port = None
        self._last_fullscreen_video_id = None
        self._last_quality_video_id = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def probe_once(self, port: int) -> bool:
        async with self._probe_lock:
            return await self._probe_once_locked(port)

    async def _probe_once_locked(self, port: int) -> bool:
        video_id, ready, fullscreen = await self._probe.inspect(port)
        if video_id is None or not ready:
            return False
        await self._select_highest_quality(port, video_id)
        if fullscreen:
            return False
        if video_id == self._last_fullscreen_video_id:
            return False
        self._last_fullscreen_video_id = video_id
        return await self._probe.fullscreen(port, video_id, True)

    async def _select_highest_quality(self, port: int, video_id: str) -> None:
        if video_id == self._last_quality_video_id:
            return
        expected_video_id = video_id.partition(":")[2] or video_id
        try:
            info = await self._probe.quality_info(port)
            if (
                expected_video_id != "default"
                and info["video_id"] not in {video_id, expected_video_id}
            ):
                return
            highest = info["available"][-1]
            if info["current"] != highest:
                selected = await self._probe.set_quality(port, highest)
                if (
                    expected_video_id != "default"
                    and selected["video_id"] not in {video_id, expected_video_id}
                ):
                    return
        except Exception:
            return
        self._last_quality_video_id = video_id

    async def force_fullscreen(self, port: int) -> bool:
        async with self._probe_lock:
            video_id, ready, fullscreen = await self._probe.inspect(port)
            if video_id is None or not ready:
                raise CommandExecutionError(
                    "youtube_video_unavailable",
                    "目前沒有可切換為全螢幕的 YouTube 影片。",
                )
            self._last_fullscreen_video_id = video_id
            if fullscreen:
                return False
            performed = await self._probe.fullscreen(port, video_id, True)
            if not performed:
                raise CommandExecutionError(
                    "youtube_video_unavailable",
                    "目前沒有可切換為全螢幕的 YouTube 影片。",
                )
            return True
    async def show_osd(self, port: int, text: str) -> None:
        show = getattr(self._probe, "show_osd", None)
        if show is not None:
            try:
                async with self._probe_lock:
                    await show(port, text)
            except Exception:
                pass

    async def adjust_playback_rate(self, port: int, direction: int) -> float:
        playback_rate = getattr(self._probe, "playback_rate", None)
        if playback_rate is None:
            raise CommandExecutionError(
                "youtube_video_unavailable",
                "目前沒有可調整倍速的影片。",
            )
        try:
            async with self._probe_lock:
                rate = await playback_rate(port, 1 if direction > 0 else -1)
        except CommandExecutionError:
            raise
        except Exception as error:
            raise CommandExecutionError(
                "youtube_video_unavailable",
                "目前沒有可調整倍速的影片。",
            ) from error
        if type(rate) not in {int, float} or not 0.25 <= float(rate) <= 4:
            raise CommandExecutionError(
                "youtube_video_unavailable",
                "目前沒有可調整倍速的影片。",
            )
        return float(rate)

    async def seek(self, port: int, direction: int) -> None:
        try:
            async with self._probe_lock:
                performed = await self._probe.seek(port, 1 if direction > 0 else -1)
        except CommandExecutionError:
            raise
        except Exception as error:
            raise CommandExecutionError(
                "youtube_video_unavailable",
                "目前沒有可快轉或倒退的影片。",
            ) from error
        if not performed:
            raise CommandExecutionError(
                "youtube_video_unavailable",
                "目前沒有可快轉或倒退的影片。",
            )

    async def quality_info(self, port: int) -> YoutubeQualityInfo:
        try:
            async with self._probe_lock:
                return await self._probe.quality_info(port)
        except CommandExecutionError:
            raise
        except Exception as error:
            raise CommandExecutionError(
                "youtube_video_unavailable",
                "目前沒有可調整畫質的 YouTube 影片。",
            ) from error

    async def set_quality(self, port: int, quality: str) -> YoutubeQualityInfo:
        if not isinstance(quality, str) or _QUALITY_CODE.fullmatch(quality) is None:
            raise CommandExecutionError(
                "youtube_quality_unavailable",
                "選擇的 YouTube 畫質目前無法使用。",
            )
        try:
            async with self._probe_lock:
                return await self._probe.set_quality(port, quality)
        except CommandExecutionError:
            raise
        except Exception as error:
            raise CommandExecutionError(
                "youtube_quality_unavailable",
                "選擇的 YouTube 畫質目前無法使用。",
            ) from error

    async def cycle_quality(self, port: int) -> str:
        try:
            async with self._probe_lock:
                return await self._probe.cycle_quality(port)
        except Exception:
            return "自動"

    async def toggle_subtitles(self, port: int) -> str:
        try:
            async with self._probe_lock:
                return await self._probe.toggle_subtitles(port)
        except Exception:
            return "切換"

    async def _run(self, port: int) -> None:
        while True:
            try:
                await self.probe_once(port)
            except Exception:
                pass
            await asyncio.sleep(self._interval_seconds)


def _is_youtube_url(url: object) -> bool:
    if not isinstance(url, str):
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "youtube.com" or host.endswith(".youtube.com")


def _is_local_debugger_url(url: object, port: int) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        parsed_port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "ws"
        and parsed.hostname == "127.0.0.1"
        and parsed_port == port
        and parsed.username is None
        and parsed.password is None
    )
