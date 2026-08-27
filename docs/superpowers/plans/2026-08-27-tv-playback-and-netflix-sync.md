# TV Playback and Netflix Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Windows 11 PC TV Box 上阻擋專用 Chrome 的通知與權限提示，以 `Chrome --app=<url>` 獨立應用程式視窗啟動無外框 Netflix，讓 YouTube／News 每支影片最多自動全螢幕一次，並以短 CDP transaction 將零機密的 Netflix 型別化情境同步到 `/remote` PWA 與 `mobile/` Expo。

**Architecture:** 保留 `Remote WebSocket → CommandBus → ApplicationManager → page controller` 單一路徑；Netflix 以 `Chrome --app=<Netflix URL>` 獨立應用視窗啟動（徹底移除 tab、omnibox 與瀏覽器外框，保留 Widevine L3 與 profile 隔離）；`CommandBus` 是 `NetflixContext` 唯一 StateStore owner，manager 與 page controller 只回傳安全 context。YouTube 使用由 manager 啟停的 1 秒 bounded probe；Netflix 每次命令、文字或複合動作各自建立 localhost CDP 短連線，在同一 transaction 完成 bounded settle 後關閉，PWA 與 Expo 只渲染 state，不推測頁面狀態。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic 2、httpx、websockets、pytest、JavaScript DOM runtime、React 19、TypeScript 5.9／6.0、Vite 7、Vitest 4、jsdom 27、Expo 57、React Native 0.86、Jest 29、PowerShell／Pester、Windows 11 Google Chrome。

## Global Constraints

- Protocol 固定為 version `1`；只為既有 `text_input` 增加 optional `submit: bool = False`，不得新增 wire message type 或改名既有 command。
- `NetflixStage` 固定為 `login | verification | browse | details | watch | unknown`；`NetflixInputKind` 固定為 `email | password | code | search | none`。
- `NetflixContext` 固定含 `stage`, `input_kind`, `has_error`, `can_submit`, `focused_title`；`focused_title` 最長 120 字且只可在 `stage=browse` 非空。
- 禁止讀取、傳輸、記錄或廣播 input `value`、輸入長度、email、password、code、Cookie、Token、Session Secret；ack、error、state 與 log 只能含固定安全文字。
- Netflix 與 YouTube CDP 只能連 `127.0.0.1` 的 controller-owned Chrome port；每次 probe／transaction 後立即關閉 socket，不得常駐連線、事件 listener 或背景長輪詢。
- 非冪等副作用採 at-most-once：發送前先記錄 video identity；OK direct-play、`Input.insertText`、submit click 或結果未知時不得重試、fallback 或重放。
- YouTube／News 只在 active 時執行 bounded 1 秒 probe；HOME、切換其他 app、關閉、崩潰與 shutdown 必須停止；同影片按 Esc 後不得拉回全螢幕。
- Netflix 非同步換頁與直接播放須在同一 short transaction 內 bounded settle；type+submit 上限 800–1200ms，detail Play 等待上限 1200ms。
- `CommandBus` 是唯一可更新與廣播 `netflix_context` 的元件；`ApplicationManager` 不得持有 StateStore 或呼叫 registry。
- 開啟非 Netflix app、HOME、回桌面、Netflix 關閉／崩潰時，`netflix_context` 必須立即設為 `None`；PWA／Expo 收到 `null` 必須卸載卡片並清空本地輸入。
- 沿用 `config/chrome-tv-profile` 與 `config/chrome-netflix-profile`；不得碰 `%LOCALAPPDATA%\Google\Chrome\User Data`、Windows 全域登錄檔或使用者日常 Chrome。
- Netflix 視窗固定以 `Chrome --app=<url>` 獨立應用程式視窗啟動，嚴禁重複夾帶 positional URL；YouTube 與 News kiosk 模式嚴禁包含 `--app` 旗標；不使用、不測試 Store PWA、WebView2、Electron 或 Android 模擬器/APK。
- 不修改 DRM、Widevine、請求、回應、Cookie、Service Worker、MediaKey 或授權交換；不持久化 Netflix 憑證。
- DOM selector 失效時回固定安全錯誤與 `stage=unknown`，降級為 D-Pad；不得拼裝 Netflix watch URL 或加入第二種 Windows／鍵盤 fallback。
- PWA 與 Expo 的 context copy、input mode、submit、send-and-clear、error copy、browse title 與 `null` 清理必須一致；Expo 額外提供既有 `TAB` command。
- 不新增 Python／npm／Expo 依賴，不修改 package／lockfile；測試使用現有 pytest、Vitest＋jsdom、Jest 與 Pester。
- 不加入、修改或刪除 `.serena/`、`.superpowers/`、專用 Chrome profile 內容或其他使用者檔案。

## File Map

| 狀態 | 檔案 | 單一責任 |
|---|---|---|
| Modify | `backend/app/applications/chrome_policy.py` | 定義兩個固定 TV Chrome 通知／權限旗標。 |
| Modify | `backend/app/applications/manager.py` | 將旗標加入兩種專用 Chrome；以 `--app=<url>` 啟動 Netflix 獨立視窗；管理 YouTube probe；讓 Netflix open／command／text 回傳 context。 |
| Create | `backend/app/applications/youtube_fullscreen.py` | 短 CDP probe、route identity、video-ready 判定、單次 `userGesture=true` 全螢幕與 task lifecycle。 |
| Modify | `backend/app/protocol.py` | 定義 `NetflixStage`、`NetflixInputKind`、`NetflixContext`，擴充 `TextInputMessage.submit` 與 `StateMessage.netflix_context`。 |
| Modify | `backend/app/state.py` | 在 `ControllerState` 保存並序列化 `netflix_context`。 |
| Modify | `backend/app/commands/ports.py` | 固定 `ApplicationPort` 的 context 回傳與 `submit` 簽章。 |
| Modify | `backend/app/commands/bus.py` | 唯一更新／清空 context，並將 `submit` 傳入 manager。 |
| Modify | `backend/app/applications/netflix_page.py` | 改為規格簽章，驗證安全 runtime result，回傳 context，實作 type+submit at-most-once。 |
| Modify | `backend/app/applications/netflix_control.js` | 型別化 context、rail/card 幾何導航、direct-play、BACK／PLAY_PAUSE 與 bounded settle。 |
| Modify | `backend/tests/test_chrome_policy.py` | 固定旗標內容與 profile 隔離。 |
| Modify | `backend/tests/test_applications.py` | manager 旗標、Netflix `--app=<url>` 獨立視窗、YouTube lifecycle 與 Netflix context 回傳。 |
| Create | `backend/tests/test_youtube_fullscreen.py` | route、ready、短 socket、at-most-once、unknown outcome 與 stop 測試。 |
| Modify | `backend/tests/test_protocol_security.py` | submit 相容、context schema、focused title 與 zero-leakage。 |
| Modify | `backend/tests/test_state.py` | context wire round-trip 與清空。 |
| Modify | `backend/tests/test_command_bus.py` | StateStore ownership、每動作更新、HOME／切 app／失敗清空。 |
| Modify | `backend/tests/test_websocket.py` | 更新 `FakeApplications` 簽章並驗證 state wire context／null。 |
| Modify | `backend/tests/test_netflix_page.py` | 安全 result、短 transaction、type+submit、direct-play outcome-unknown 與無重試。 |
| Modify | `frontend/src/netflix/netflixControl.test.ts` | 以 jsdom 真實載入 runtime，鎖定 context、rail、direct-play、BACK 與零回讀。 |
| Modify | `frontend/src/types/protocol.ts` | PWA 的 Netflix 型別、state property 與 optional submit。 |
| Modify | `frontend/src/api/controllerSocket.ts` | `sendText(text, submit = false): string | null`。 |
| Modify | `frontend/src/api/controllerSocket.test.ts` | PWA submit wire serialization 與預設相容。 |
| Modify | `frontend/src/remote/RemotePage.tsx` | 非侵入式 inline context card、typed input、send-and-clear、waiting 與 null 清理。 |
| Modify | `frontend/src/remote/RemotePage.test.tsx` | email／password／code／browse／error／submit／null 的 PWA 契約。 |
| Modify | `frontend/src/styles.css` | Context Card、error 與 waiting 的既有視覺系統樣式。 |
| Modify | `mobile/src/types/protocol.ts` | Expo 的 Netflix 型別、state property、optional submit 與 `TAB` command。 |
| Modify | `mobile/src/api/controllerSocket.ts` | `sendTextInput(text, submit = false): Promise<Acknowledgement>`。 |
| Modify | `mobile/src/api/controllerSocket.test.ts` | Expo submit wire serialization 與預設相容。 |
| Modify | `mobile/src/components/TextInputModal.tsx` | 對齊 email／password／code keyboard、遮蔽與 `onSend(text, submit)` 簽章。 |
| Modify | `mobile/src/screens/RemoteScreen.tsx` | Inline Context Card、TAB、send-and-clear、waiting 與 null 清理。 |
| Modify | `mobile/src/screens/RemoteScreen.test.tsx` | Expo context／TAB／submit／清空／安全輸入契約。 |
| Modify | `README.md` | 使用者可見的通知、YouTube fullscreen、Netflix safe context 與兩種 remote 行為。 |
| Modify | `docs/ARCHITECTURE.md` | ownership、短 CDP、YouTube lifecycle、Netflix transaction 與雙 client data flow。 |
| Modify | `docs/PROTOCOL.md` | version 1 optional submit 與 optional Netflix context wire schema。 |
| Modify | `docs/WINDOWS_SETUP.md` | 專用 Chrome profiles、實機驗證與安全測試帳號前置。 |
| Verify unchanged | `backend/app/controller.py`, `backend/app/websocket/registry.py` | 繼續依 `CommandOutcome.state_changed` 廣播；不得取得 Netflix ownership。 |
| Verify unchanged | `frontend/package.json`, `mobile/package.json`, lockfiles | 不新增依賴或 script。 |

---

### Task 1: TV Chrome Notification and Permission Policy

**Files:**
- Modify: `backend/app/applications/chrome_policy.py:8-14`
- Modify: `backend/app/applications/manager.py:162-203`
- Modify: `backend/tests/test_chrome_policy.py`
- Modify: `backend/tests/test_applications.py:224-264`

**Interfaces:**
- Consumes: `ApplicationManager._chrome_kiosk_args(url: str) -> list[str]`、`_chrome_desktop_args(url: str, profile_dir: Path) -> list[str]`。
- Produces: `TV_CHROME_NOTIFICATION_FLAGS: list[str]`，值依序固定為 `--disable-notifications`, `--deny-permission-prompts`。
- Produces: YouTube／News 與 Netflix argv 都各含兩旗標一次，profile 仍分別為 `config/chrome-tv-profile` 與 `config/chrome-netflix-profile`。

- [ ] **Step 1: 寫入會先失敗的 policy 與 argv tests**

```python
# backend/tests/test_chrome_policy.py
from app.applications.chrome_policy import TV_CHROME_NOTIFICATION_FLAGS


def test_tv_notification_flags_are_fixed_and_minimal() -> None:
    assert TV_CHROME_NOTIFICATION_FLAGS == [
        "--disable-notifications",
        "--deny-permission-prompts",
    ]
```

```python
# backend/tests/test_applications.py
@pytest.mark.parametrize("app", [ActiveApp.YOUTUBE, ActiveApp.NETFLIX])
def test_tv_chrome_denies_notification_and_permission_prompts(app: ActiveApp) -> None:
    manager, launcher, _, _ = make_manager()
    asyncio.run(manager.open(app))
    argv = launcher.calls[0]
    assert argv.count("--disable-notifications") == 1
    assert argv.count("--deny-permission-prompts") == 1
    expected_profile = "chrome-netflix-profile" if app is ActiveApp.NETFLIX else "chrome-tv-profile"
    profile_arg = next(argument for argument in argv if argument.startswith("--user-data-dir="))
    assert expected_profile in profile_arg
    assert "Google/Chrome/User Data" not in profile_arg.replace("\\", "/")
```

- [ ] **Step 2: 執行 RED**

Run（repo root）：`.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_chrome_policy.py backend\tests\test_applications.py -k "notification_flags or denies_notification"`

Expected: collection FAIL with `ImportError: cannot import name 'TV_CHROME_NOTIFICATION_FLAGS'`。

- [ ] **Step 3: 加入最小固定 policy 並由兩種 argv 共用**

```python
# backend/app/applications/chrome_policy.py
TV_CHROME_NOTIFICATION_FLAGS = [
    "--disable-notifications",
    "--deny-permission-prompts",
]
```

```python
# backend/app/applications/manager.py
from app.applications.chrome_policy import TV_CHROME_NOTIFICATION_FLAGS

# _chrome_kiosk_args() 與 _chrome_desktop_args() 的 return list 在 URL 前各加入：
*TV_CHROME_NOTIFICATION_FLAGS,
```

兩個 builder 各展開一次；不得把旗標放進全域 Chrome policy、registry writer 或使用者 profile。

- [ ] **Step 4: 執行 GREEN**

Run（repo root）：`.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_chrome_policy.py backend\tests\test_applications.py`

Expected: PASS；兩種 argv 仍保留原本 localhost debug port 與各自 profile。

- [ ] **Step 5: Commit**

```bash
git add backend/app/applications/chrome_policy.py backend/app/applications/manager.py backend/tests/test_chrome_policy.py backend/tests/test_applications.py
git commit -m "feat: suppress TV Chrome permission prompts"
```

### Task 2: Netflix Standalone Chrome App Shell

**Files:**
- Modify: `backend/app/applications/manager.py:184-204`
- Modify: `backend/tests/test_applications.py:224-264`

**Interfaces:**
- Consumes: `ApplicationManager._chrome_desktop_args(url: str, profile_dir: Path) -> list[str]`、Task 1 `TV_CHROME_NOTIFICATION_FLAGS`。
- Produces: Netflix Chrome argv 包含單一 `f"--app={url}"` 參數，無任何等於 positional Netflix URL 的參數。
- Produces: YouTube 與 News kiosk argv 不含 `--app=`。
- Produces: 保留 `--start-fullscreen`、`--user-data-dir=...`、`--remote-debugging-port=...`、`--remote-debugging-address=127.0.0.1`、`--disable-extensions` 與 `TV_CHROME_NOTIFICATION_FLAGS`。
- Produces: reopen／HOME／PID-HWND ownership 不變。

- [ ] **Step 1: 寫入會先失敗的 standalone app shell 與 argv tests**

```python
# backend/tests/test_applications.py
def test_netflix_chrome_launches_as_standalone_app_window_without_positional_url() -> None:
    manager, launcher, _, _ = make_manager()
    asyncio.run(manager.open(ActiveApp.NETFLIX))
    argv = launcher.calls[0]
    expected_app_arg = f"--app={manager._settings.urls.netflix}"
    assert argv.count(expected_app_arg) == 1
    assert any(arg.startswith("--app=") for arg in argv)
    assert not any(arg == manager._settings.urls.netflix for arg in argv)
    assert argv.count("--start-fullscreen") == 1
    assert argv.count("--disable-extensions") == 1
    assert argv.count("--remote-debugging-address=127.0.0.1") == 1
    assert any(arg.startswith("--remote-debugging-port=") for arg in argv)
    assert any(arg.startswith("--user-data-dir=") and "chrome-netflix-profile" in arg for arg in argv)


def test_youtube_and_news_kiosk_args_do_not_contain_app_flag() -> None:
    manager, launcher, _, _ = make_manager()
    asyncio.run(manager.open(ActiveApp.YOUTUBE))
    youtube_argv = launcher.calls[0]
    assert not any(arg.startswith("--app=") for arg in youtube_argv)
    assert youtube_argv[-1] == manager._settings.urls.youtube
```

- [ ] **Step 2: 執行 RED**

Run（repo root）：`.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_applications.py -k "standalone_app or do_not_contain_app_flag"`

Expected: FAIL；`argv` 包含 positional URL 而無 `--app=` 旗標。

|- [ ] **Step 3: 將 `_chrome_desktop_args()` 的 positional URL 改為 `f"--app={url}"` 且不 append url**

```python
# backend/app/applications/manager.py
def _chrome_desktop_args(self, url: str, profile_dir: Path) -> list[str]:
    chrome = self._executables.get("chrome")
    if chrome is None:
        raise CommandExecutionError(
            "chrome_not_found",
            "未安裝或尚未設定 Chrome。請安裝 Chrome，或在 applications.chrome_path 指定路徑。",
        )
    mark_chrome_profile_clean_exit(profile_dir)
    return [
        chrome.as_posix(),
        f"--user-data-dir={profile_dir}",
        "--start-fullscreen",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={self._netflix_debug_port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        *CHROME_RESTORE_SUPPRESS_ARGS,
        *TV_CHROME_NOTIFICATION_FLAGS,
        f"--app={url}",
    ]
```

- [ ] **Step 4: 執行 GREEN**

Run（repo root）：`.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_applications.py`

Expected: PASS；Netflix argv 包含唯一 `--app=<url>`，YouTube kiosk 維持原狀，reopen / HOME / PID-HWND 測試全數通過。

- [ ] **Step 5: Commit**

```bash
git add backend/app/applications/manager.py backend/tests/test_applications.py
git commit -m "feat: launch Netflix as standalone TV app"
```

---

### Task 3: YouTube Fullscreen Controller and Manager Lifecycle

**Files:**
- Create: `backend/app/applications/youtube_fullscreen.py`
- Create: `backend/tests/test_youtube_fullscreen.py`
- Modify: `backend/app/applications/manager.py:116-155,206-310,328-345,457-464`
- Modify: `backend/tests/test_applications.py:19-180,224-410`

**Interfaces:**
- Consumes: controller-owned YouTube／News debug `port: int`、`httpx.AsyncClient`、`websockets.connect`、CDP `Runtime.evaluate`。
- Produces: `extract_video_identity(url: str) -> str | None`，支援 `/watch?v=`, `#/watch?v=`, `/shorts/<id>`, `/live/<id>`。
- Produces: `YoutubeFullscreenController(interval_seconds: float = 1.0, timeout: float = 0.8)`。
- Produces: `start(port: int) -> None`, `stop() -> None`, `probe_once(port: int) -> bool`；`start` idempotent，`stop` 等待 task 結束。
- Lifecycle: `ApplicationManager` 在成功開啟 YouTube／News 後 `await start(_debug_port)`；離開兩者、HOME、切 app、關閉、失敗 rollback 與 shutdown 均 `await stop()`。

- [ ] **Step 1: 寫 route、ready 與 at-most-once failing tests**

```python
# backend/tests/test_youtube_fullscreen.py
import asyncio
import json

import pytest

from app.applications.youtube_fullscreen import YoutubeFullscreenController, extract_video_identity


@pytest.mark.parametrize(
    ("url", "identity"),
    [
        ("https://www.youtube.com/watch?v=alpha", "watch:alpha"),
        ("https://www.youtube.com/tv#/watch?v=beta", "watch:beta"),
        ("https://www.youtube.com/shorts/gamma?feature=share", "shorts:gamma"),
        ("https://www.youtube.com/live/delta", "live:delta"),
        ("https://www.youtube.com/tv#/browse", None),
    ],
)
def test_extract_video_identity_covers_supported_routes(url: str, identity: str | None) -> None:
    assert extract_video_identity(url) == identity


class FakeProbe:
    def __init__(self) -> None:
        self.fullscreen_calls: list[tuple[str, bool]] = []
        self.fail_after_send = False

    async def inspect(self, port: int) -> tuple[str, bool, bool]:
        assert port == 9222
        return "watch:alpha", True, False

    async def fullscreen(self, port: int, video_id: str, user_gesture: bool) -> None:
        self.fullscreen_calls.append((video_id, user_gesture))
        if self.fail_after_send:
            raise TimeoutError


async def exercise_unknown_outcome() -> list[tuple[str, bool]]:
    probe = FakeProbe()
    probe.fail_after_send = True
    controller = YoutubeFullscreenController(probe=probe)
    with pytest.raises(TimeoutError):
        await controller.probe_once(9222)
    assert await controller.probe_once(9222) is False
    return probe.fullscreen_calls


def test_marks_video_before_send_and_never_retries_unknown_outcome() -> None:
    assert asyncio.run(exercise_unknown_outcome()) == [("watch:alpha", True)]
```

`FakeProbe.inspect()` 另以 `ready=False`、`fullscreen=True`、相同 identity 連續 probe 建立 table tests，均 assert `fullscreen_calls == []` 或只一筆；以 fake short-session assert 每次 inspect/fullscreen 都離開 async context。

- [ ] **Step 2: 寫 manager lifecycle failing test**

```python
# backend/tests/test_applications.py
@dataclass
class FakeYoutubeFullscreen:
    started: list[int] = field(default_factory=list)
    stop_calls: int = 0

    async def start(self, port: int) -> None:
        self.started.append(port)

    async def stop(self) -> None:
        self.stop_calls += 1


def test_youtube_fullscreen_probe_starts_only_for_youtube_and_news_and_stops_on_home() -> None:
    fullscreen = FakeYoutubeFullscreen()
    manager, _, _, _ = make_manager(youtube_fullscreen=fullscreen, debug_port=9222)
    asyncio.run(manager.open(ActiveApp.YOUTUBE))
    assert fullscreen.started == [9222]
    asyncio.run(manager.return_home())
    assert fullscreen.stop_calls == 1
```

同檔以完整 function 分別覆蓋 `open(ActiveApp.NETFLIX)` 前停止、`leave_to_desktop()`、YouTube launch failure、News channel replacement與 `shutdown()`；每個 assert stop count，不以 sleep 猜測 task 狀態。

- [ ] **Step 3: 執行 RED**

Run（repo root）：`.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_youtube_fullscreen.py backend\tests\test_applications.py -k "fullscreen or probe"`

Expected: collection FAIL，`app.applications.youtube_fullscreen` 不存在。

- [ ] **Step 4: 實作 route identity 與窄 controller**

```python
# backend/app/applications/youtube_fullscreen.py
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol
from urllib.parse import parse_qs, urlparse


class YoutubeProbe(Protocol):
    async def inspect(self, port: int) -> tuple[str | None, bool, bool]: ...
    async def fullscreen(self, port: int, video_id: str, user_gesture: bool) -> None: ...


def extract_video_identity(url: str) -> str | None:
    parsed = urlparse(url)
    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if parsed.path.endswith("/watch") and query_id:
        return f"watch:{query_id}"
    fragment = parsed.fragment
    if fragment.startswith("/watch?"):
        hash_id = parse_qs(fragment.partition("?")[2]).get("v", [None])[0]
        if hash_id:
            return f"watch:{hash_id}"
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[-2] in {"shorts", "live"}:
        return f"{parts[-2]}:{parts[-1]}"
    return None


class YoutubeFullscreenController:
    def __init__(
        self,
        interval_seconds: float = 1.0,
        timeout: float = 0.8,
        *,
        probe: YoutubeProbe | None = None,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._timeout = timeout
        self._probe = probe or ShortCdpYoutubeProbe(timeout)
        self._task: asyncio.Task[None] | None = None
        self._last_fullscreen_video_id: str | None = None

    async def start(self, port: int) -> None:
        await self.stop()
        self._task = asyncio.create_task(self._run(port))

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def probe_once(self, port: int) -> bool:
        video_id, ready, fullscreen = await self._probe.inspect(port)
        if video_id is None or not ready or fullscreen:
            return False
        if video_id == self._last_fullscreen_video_id:
            return False
        self._last_fullscreen_video_id = video_id
        await self._probe.fullscreen(port, video_id, True)
        return True

    async def _run(self, port: int) -> None:
        while True:
            try:
                await self.probe_once(port)
            except Exception:
                pass
            await asyncio.sleep(self._interval_seconds)
```

`ShortCdpYoutubeProbe` 使用 `GET http://127.0.0.1:{port}/json/list` 選唯一 YouTube top-level target；每個 `inspect`／`fullscreen` 各自 `async with websockets.connect(...)`，離開即 close。Inspect expression 只回 `{url, ready: video?.readyState >= 2, fullscreen: document.fullscreenElement !== null}`；fullscreen expression 只執行 `#movie_player || video` 的 `requestFullscreen()`，CDP params 明確含 `"userGesture": True`，無 keypress、DOM click 或第二次送出。

- [ ] **Step 5: 將 manager lifecycle 接上 controller**

```python
# backend/app/applications/manager.py constructor
self._youtube_fullscreen = youtube_fullscreen or YoutubeFullscreenController()

# _launch_and_track() 成功並完成 adfilter attach 後
if app in {ActiveApp.YOUTUBE, ActiveApp.NEWS}:
    await self._youtube_fullscreen.start(self._debug_port)

# _close_apps() 在停止 YouTube／News tracked process 前
if any(app in {ActiveApp.YOUTUBE, ActiveApp.NEWS} for app in apps):
    await self._youtube_fullscreen.stop()

# shutdown() 第一個動作
await self._youtube_fullscreen.stop()
```

`open()`、`open_news()`、`search_youtube()` 既有 `_close_apps()` 保證 replacement 先 stop；launch／window discovery／adfilter 後若 start 失敗，停止並 rollback 新 tracked process，不留下 background task。

- [ ] **Step 6: 執行 GREEN**

Run（repo root）：`.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_youtube_fullscreen.py backend\tests\test_applications.py`

Expected: PASS；unknown outcome test 只發一個 fullscreen CDP command，manager lifecycle 沒有 pending task warning。

- [ ] **Step 7: Commit**

```bash
git add backend/app/applications/youtube_fullscreen.py backend/app/applications/manager.py backend/tests/test_youtube_fullscreen.py backend/tests/test_applications.py
git commit -m "feat: auto fullscreen YouTube videos once"
```

---

### Task 4: Netflix Context Protocol, State, Ports, and CommandBus Ownership

**Files:**
- Modify: `backend/app/protocol.py:9-14,89-103,150-160`
- Modify: `backend/app/state.py:29-51`
- Modify: `backend/app/commands/ports.py:3-29`
- Modify: `backend/app/commands/bus.py:77-354`
- Modify: `backend/tests/test_protocol_security.py:41-100`
- Modify: `backend/tests/test_state.py`
- Modify: `backend/tests/test_command_bus.py:19-76,207-330`
- Modify: `backend/tests/test_websocket.py:30-61`

**Interfaces:**
- Produces: `NetflixStage`, `NetflixInputKind`, `NetflixContext` exactly as Global Constraints。
- Produces: `TextInputMessage.submit: bool = False`, `StateMessage.netflix_context: NetflixContext | None = None`, `ControllerState.netflix_context: NetflixContext | None = None`。
- Produces: `ApplicationPort.open(app: ActiveApp) -> NetflixContext | None`。
- Produces: `ApplicationPort.forward_command(command: Command) -> NetflixContext | None`。
- Produces: `ApplicationPort.type_text(text: str, submit: bool = False) -> NetflixContext | None`。
- Consumes in `CommandBus`: only returned context；bus writes it to `StateStore`, and all non-Netflix transitions write `None`。

- [ ] **Step 1: 寫 protocol schema 與 zero-leakage failing tests**

```python
# backend/tests/test_protocol_security.py
from pydantic import ValidationError

from app.protocol import NetflixContext, NetflixInputKind, NetflixStage, TextInputMessage


def test_text_input_submit_is_backward_compatible_and_typed() -> None:
    base = {"version": 1, "type": "text_input", "request_id": "text-1", "text": "secret"}
    assert TextInputMessage.model_validate(base).submit is False
    assert TextInputMessage.model_validate({**base, "submit": True}).submit is True
    with pytest.raises(ValidationError):
        TextInputMessage.model_validate({**base, "submit": "true"})


def test_netflix_context_allows_title_only_in_browse_and_forbids_secret_fields() -> None:
    context = NetflixContext(
        stage=NetflixStage.BROWSE,
        input_kind=NetflixInputKind.NONE,
        focused_title="Example",
    )
    assert context.model_dump() == {
        "stage": "browse",
        "input_kind": "none",
        "has_error": False,
        "can_submit": False,
        "focused_title": "Example",
    }
    with pytest.raises(ValidationError):
        NetflixContext(stage="login", input_kind="password", focused_title="forbidden")
    for field in ("value", "length", "email", "password", "code", "cookie", "token"):
        with pytest.raises(ValidationError):
            NetflixContext.model_validate({
                "stage": "login",
                "input_kind": "password",
                "has_error": False,
                "can_submit": True,
                "focused_title": None,
                field: "secret",
            })
```

- [ ] **Step 2: 寫 StateStore ownership 與 invalidation failing tests**

```python
# backend/tests/test_command_bus.py
LOGIN_CONTEXT = NetflixContext(
    stage=NetflixStage.LOGIN,
    input_kind=NetflixInputKind.EMAIL,
    can_submit=True,
)
BROWSE_CONTEXT = NetflixContext(
    stage=NetflixStage.BROWSE,
    input_kind=NetflixInputKind.NONE,
    focused_title="Example",
)


async def context_ownership_scenario() -> None:
    bus, applications, _, _ = make_bus()
    applications.next_context = LOGIN_CONTEXT
    opened = await bus.dispatch_command(Command.OPEN_NETFLIX)
    assert opened.state.netflix_context == LOGIN_CONTEXT

    applications.next_context = BROWSE_CONTEXT
    moved = await bus.dispatch_command(Command.NAV_RIGHT)
    assert moved.state.netflix_context == BROWSE_CONTEXT

    home = await bus.dispatch_command(Command.HOME)
    assert home.state.netflix_context is None


def test_command_bus_alone_owns_netflix_context_and_clears_home() -> None:
    asyncio.run(context_ownership_scenario())


async def submit_scenario() -> None:
    bus, applications, _, _ = make_bus(initial=ControllerState(active_app=ActiveApp.NETFLIX))
    applications.next_context = LOGIN_CONTEXT
    outcome = await bus.dispatch_text(TextInputMessage(
        version=1,
        type="text_input",
        request_id="text-1",
        text="secret",
        submit=True,
    ))
    assert applications.typed == [("secret", True)]
    assert outcome.state.netflix_context == LOGIN_CONTEXT


def test_command_bus_forwards_submit_once_and_stores_only_returned_context() -> None:
    asyncio.run(submit_scenario())
```

更新 `FakeApplications` 為 `next_context: NetflixContext | None`，`typed: list[tuple[str, bool]]`，三個方法回傳 `next_context`；`test_websocket.py` 的 fake 同步採完全相同簽章。另以具名 functions 分別驗證 `OPEN_YOUTUBE`, `OPEN_NEWS`, `OPEN_LIVE_TV`, `OPEN_BROWSER`, `dispatch_search`, HOME、desktop rollback 與 launch error 都把既有 context 清為 `None`，並驗證 `ControllerState.to_wire().netflix_context` 的 object／null。

- [ ] **Step 3: 執行 RED**

Run（repo root）：`.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_protocol_security.py backend\tests\test_state.py backend\tests\test_command_bus.py backend\tests\test_websocket.py`

Expected: FAIL，缺少 `NetflixContext`／`submit`／state property，Fake method 不接受 `submit`。

- [ ] **Step 4: 實作 frozen protocol models 與 state wire**

```python
# backend/app/protocol.py
class NetflixStage(StrEnum):
    LOGIN = "login"
    VERIFICATION = "verification"
    BROWSE = "browse"
    DETAILS = "details"
    WATCH = "watch"
    UNKNOWN = "unknown"


class NetflixInputKind(StrEnum):
    EMAIL = "email"
    PASSWORD = "password"
    CODE = "code"
    SEARCH = "search"
    NONE = "none"


class NetflixContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: NetflixStage
    input_kind: NetflixInputKind
    has_error: bool = False
    can_submit: bool = False
    focused_title: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def title_is_browse_only(self) -> NetflixContext:
        if self.stage is not NetflixStage.BROWSE and self.focused_title is not None:
            raise ValueError("focused_title is only valid during browse")
        return self


class TextInputMessage(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["text_input"]
    request_id: str = Field(min_length=1, max_length=64, pattern=REQUEST_ID_PATTERN)
    text: str = Field(min_length=1, max_length=256)
    submit: bool = Field(default=False, strict=True)


class StateMessage(WireModel):
    version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    type: Literal["state"] = "state"
    active_app: str
    focused_tile: str
    volume: int = Field(ge=0, le=100)
    muted: bool
    channel_number: int | None = None
    channel_name: str | None = Field(default=None, max_length=120)
    status_message: str | None = Field(default=None, max_length=256)
    error_message: str | None = Field(default=None, max_length=256)
    netflix_context: NetflixContext | None = None
```

```python
# backend/app/state.py ControllerState 與 to_wire()
netflix_context: NetflixContext | None = None

# StateMessage(...)
netflix_context=self.netflix_context,
```

- [ ] **Step 5: 改 ports 與 bus，使 context 更新只有一個 owner**

```python
# backend/app/commands/ports.py
from app.protocol import Command, NetflixContext, PointerActionMessage

class ApplicationPort(Protocol):
    async def open(self, app: ActiveApp) -> NetflixContext | None: ...
    async def open_news(self, url: str) -> None: ...
    async def search_youtube(self, query: str) -> None: ...
    async def return_home(self) -> None: ...
    async def leave_to_desktop(self) -> None: ...
    async def forward_command(self, command: Command) -> NetflixContext | None: ...
    async def type_text(self, text: str, submit: bool = False) -> NetflixContext | None: ...
    def require_input_target(self, app: ActiveApp) -> None: ...
```

```python
# backend/app/commands/bus.py dispatch_text Netflix branch
context = await self._applications.type_text(message.text, submit=message.submit)
state = await self._state.update(
    netflix_context=context,
    error_message=None,
    status_message=None,
)
return CommandOutcome(True, state)

# Netflix forward branch
context = await self._applications.forward_command(command)
state = await self._state.update(
    netflix_context=context,
    error_message=None,
    status_message=None,
)
return CommandOutcome(True, state)

# OPEN_NETFLIX branch
context = await self._applications.open(ActiveApp.NETFLIX)
state = await self._state.update(
    active_app=ActiveApp.NETFLIX,
    netflix_context=context,
    channel_number=None,
    channel_name=None,
    error_message=None,
    status_message=None,
)
return CommandOutcome(True, state)
```

每個非 Netflix success／rollback 的既有 `_state.update()` 明確加 `netflix_context=None`；錯誤若 manager 已 rollback 至 launcher 也清空。不要在 manager 注入 StateStore，不要直接 registry.broadcast。

- [ ] **Step 6: 執行 GREEN**

Run（repo root）：`.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_protocol_security.py backend\tests\test_state.py backend\tests\test_command_bus.py backend\tests\test_websocket.py`

Expected: PASS；舊 payload 無 `submit` 仍通過，state JSON 僅多 optional `netflix_context`。

- [ ] **Step 7: Commit**

```bash
git add backend/app/protocol.py backend/app/state.py backend/app/commands/ports.py backend/app/commands/bus.py backend/tests/test_protocol_security.py backend/tests/test_state.py backend/tests/test_command_bus.py backend/tests/test_websocket.py
git commit -m "feat: broadcast typed Netflix context"
```

---

### Task 5: Netflix Runtime Context, Rail Navigation, Type+Submit, and Direct Play

**Files:**
- Modify: `backend/app/applications/netflix_control.js`
- Modify: `backend/app/applications/netflix_page.py:16-374`
- Modify: `backend/app/applications/manager.py:116-155,206-240,349-415`
- Modify: `backend/tests/test_netflix_page.py`
- Modify: `backend/tests/test_applications.py:139-168,243-286`
- Modify: `frontend/src/netflix/netflixControl.test.ts`

**Interfaces:**
- Consumes: Task 4 `NetflixContext`, `NetflixStage`, `NetflixInputKind`；Task 2 & 3 manager lifecycle；localhost Netflix debug port。
- Produces: `NetflixPageController(port: int, timeout: float = 8.0, runtime_path: Path | None = None)`。
- Produces: `execute(command: Command) -> NetflixContext`、`type_text(text: str, submit: bool = False) -> NetflixContext`，完全符合 ports。
- Produces: `initialize() -> NetflixContext`，只執行可安全重試的 `FOCUS_PRIMARY` 並供 manager 開啟／重用 Netflix 時取得第一筆 context。
- Produces runtime: `globalThis.__freeTvNetflixControl.run(action, previousFocus) -> Promise<RuntimeResult>`；success result 必含安全 `context`。
- Internal actions 固定加入 `READ_CONTEXT`, `SUBMIT_PRIMARY`；wire commands 不變。`OK`、`SUBMIT_PRIMARY` 與 insertText 都是 at-most-once。

- [ ] **Step 1: 寫真實 runtime context 與 rail fixture failing tests**

```ts
// frontend/src/netflix/netflixControl.test.ts
it('returns email password code and browse contexts without reading input values', async () => {
  document.body.innerHTML = '<form><input id="email" type="email"><button type="submit">下一步</button></form>'
  const email = document.querySelector('input') as HTMLInputElement
  Object.defineProperty(email, 'value', { get: () => { throw new Error('secret read') }, set: () => undefined })
  const login = await runtime().run('READ_CONTEXT', null)
  expect(login.context).toEqual({
    stage: 'login', input_kind: 'email', has_error: false, can_submit: true, focused_title: null,
  })

  document.body.innerHTML = '<input inputmode="numeric" autocomplete="one-time-code"><button>驗證</button>'
  const verification = await runtime().run('READ_CONTEXT', null)
  expect(verification.context).toMatchObject({ stage: 'verification', input_kind: 'code' })
  expect(JSON.stringify(verification.context)).not.toMatch(/value|length|password|code\s*:/i)
})

it('moves within the active rail then chooses the closest x card in the adjacent rail', async () => {
  document.body.innerHTML = [
    '<div class="lolomoRow" id="top"><div class="title-card">A</div><div class="title-card">B</div></div>',
    '<div class="lolomoRow" id="bottom"><div class="title-card">C</div><div class="title-card">D</div></div>',
  ].join('')
  const [a, b, c, d] = [...document.querySelectorAll('.title-card')]
  setRect(a, 0, 0); setRect(b, 180, 0); setRect(c, 20, 140); setRect(d, 230, 140)
  a.setAttribute('tabindex', '0'); b.setAttribute('tabindex', '0')
  c.setAttribute('tabindex', '0'); d.setAttribute('tabindex', '0')
  a.focus()
  await runtime().run('NAV_RIGHT', null)
  expect(document.activeElement).toBe(b)
  await runtime().run('NAV_DOWN', null)
  expect(document.activeElement).toBe(d)
})
```

同檔用完整 fixture functions 覆蓋：header／`.handle-prev`／`.handle-next`／preview popover 被忽略；非 browse 的 title 為 null；title 去 HTML 並截到 120；error 只回 boolean；watch BACK、details BACK、PLAY_PAUSE readyState；OK 已有 Play 立即點一次；無 Play 時 card click 後 1200ms 內 detail Play 點一次；timeout 回固定 error 且不重點。

- [ ] **Step 2: 寫 page controller context、submit 與 unknown-outcome failing tests**

```python
# backend/tests/test_netflix_page.py
async def type_submit_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = make_controller(tmp_path, port=9223)
    socket = FakeSocket(runtime_results=[
        {"ok": True, "status": "focused", "focus": valid_focus(), "context": login_context("password")},
        {"ok": True, "status": "submitted", "context": login_context("none")},
    ])
    connect = FakeConnect([socket])
    monkeypatch.setattr("app.applications.netflix_page.websockets.connect", connect)
    context = await controller.type_text("secret", submit=True)
    methods = [message["method"] for message in socket.sent]
    assert methods.count("Input.insertText") == 1
    assert methods.count("Runtime.evaluate") >= 2
    assert context.input_kind is NetflixInputKind.NONE
    assert "secret" not in repr(context)


def test_type_submit_runs_once_in_one_short_transaction_and_returns_safe_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(type_submit_scenario(tmp_path, monkeypatch))


def test_non_browse_runtime_title_is_rejected_without_exposing_payload(tmp_path: Path) -> None:
    controller = make_controller(tmp_path, port=9223)
    with pytest.raises(CommandExecutionError) as caught:
        controller._accept_runtime_result({
            "ok": True,
            "status": "focused",
            "focus": valid_focus(),
            "context": {
                "stage": "login",
                "input_kind": "password",
                "has_error": False,
                "can_submit": True,
                "focused_title": "must-not-pass",
            },
        })
    assert caught.value.code == "netflix_controller_unavailable"
```

沿用既有 `FakeSocket`／`FakeConnect` 另寫 `test_insert_text_ack_loss_does_not_send_submit_or_retry`、`test_submit_ack_loss_does_not_reconnect_or_repeat_click`、`test_ok_direct_play_timeout_is_not_retried`、`test_each_execute_closes_socket_after_bounded_settle`；每個明確 assert connect call 數為 1、side-effect expression 數為 1、socket closed 為 true。

- [ ] **Step 3: 執行 RED**

Run（repo root）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_netflix_page.py backend\tests\test_applications.py
Push-Location frontend; npm test -- src/netflix/netflixControl.test.ts; Pop-Location
```

Expected: FAIL；`execute()`／`type_text()` 回傳 `None`，runtime result 無 `context`，rail/direct-play fixtures 不符合新契約。

- [ ] **Step 4: 實作安全 context extractor 與 async composites**

```js
// backend/app/applications/netflix_control.js
const safeText = (element) => (element?.textContent || '').replace(/<[^>]*>/g, '').trim().slice(0, 120)
const editable = () => [...document.querySelectorAll('input,textarea,[contenteditable="true"]')]
  .find((element) => visible(element)) || null

const inputKind = (element) => {
  if (!(element instanceof HTMLElement)) return 'none'
  const type = (element.getAttribute('type') || '').toLowerCase()
  const autocomplete = (element.getAttribute('autocomplete') || '').toLowerCase()
  const inputmode = (element.getAttribute('inputmode') || '').toLowerCase()
  if (type === 'password' || autocomplete.includes('password')) return 'password'
  if (autocomplete === 'one-time-code' || inputmode === 'numeric') return 'code'
  if (type === 'email' || autocomplete === 'email' || autocomplete === 'username') return 'email'
  if (type === 'search' || element.getAttribute('role') === 'searchbox') return 'search'
  return 'none'
}

const netflixContext = () => {
  const path = globalThis.location.pathname
  const field = editable()
  const kind = inputKind(field)
  const stage = path.includes('/watch/') ? 'watch'
    : document.querySelector('.detail-modal,.previewModal--wrapper') ? 'details'
    : kind === 'code' ? 'verification'
    : kind !== 'none' ? 'login'
    : document.querySelector('.lolomoRow,.rowContainer') ? 'browse'
    : 'unknown'
  const focused = document.activeElement?.closest?.('.title-card,.slider-item')
  return {
    stage,
    input_kind: kind,
    has_error: Boolean(document.querySelector('[role="alert"],.ui-message-error,.inputError')),
    can_submit: Boolean([...document.querySelectorAll('button,[role="button"]')].find((button) => visible(button) && /next|continue|sign in|verify|下一步|繼續|登入|驗證/i.test(safeText(button)))),
    focused_title: stage === 'browse' && focused ? safeText(focused) : null,
  }
}

const settle = async (predicate, timeoutMs) => {
  const deadline = performance.now() + timeoutMs
  while (performance.now() < deadline) {
    const result = predicate()
    if (result) return result
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  return null
}
```

`run()` 改為 async 並讓每個 success result 帶 `context: netflixContext()`。NAV_LEFT／RIGHT 只在 current rail 可見卡片選鄰卡；NAV_UP／DOWN 只選相鄰 rail 中 X 中心差最小卡片；candidate selector 排除 header、handles 與 preview popover。`OK` 在 browse 先找 visible Play／Resume，一次 click；否則一次 card click，再 `settle(..., 1200)` 找 detail Play 並一次 click，timeout 回 `netflix_direct_play_unavailable`，不得再次 card click。`SUBMIT_PRIMARY` 一次 click visible primary submit 後 `settle(() => page signature changed, 1200)`；`BACK` 依 watch/details/browse 分支；`PLAY_PAUSE` 只接受 `readyState >= 2` 的目前 document video。

- [ ] **Step 5: 讓 Python controller 驗證並回傳 context**

```python
# backend/app/applications/netflix_page.py
Operation = Callable[[Any], Awaitable[NetflixContext]]

class NetflixPageController:
    def __init__(self, port: int, timeout: float = 8.0, runtime_path: Path | None = None) -> None:
        self._port = port
        self._timeout = timeout
        self._runtime_source = (runtime_path or Path(__file__).with_name("netflix_control.js")).read_text(encoding="utf-8")
        self._focus: FocusFingerprint | None = None
        self._command_id = 0

    async def initialize(self) -> NetflixContext:
        async def operation(socket: Any) -> NetflixContext:
            result = await self._run_runtime(socket, NetflixAction.FOCUS_PRIMARY)
            return self._accept_runtime_result(result)

        return await self._run_transaction(operation)

    async def execute(self, command: Command) -> NetflixContext:
        action = NETFLIX_ACTIONS.get(command)
        if action is None:
            raise CommandExecutionError("command_not_supported", "Netflix 不支援這個遙控指令。")

        async def operation(socket: Any) -> NetflixContext:
            result = await self._run_runtime(socket, action)
            return self._accept_runtime_result(result)

        return await self._run_transaction(operation)

    async def type_text(self, text: str, submit: bool = False) -> NetflixContext:
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        async def operation(socket: Any) -> NetflixContext:
            focused = self._accept_runtime_result(
                await self._run_runtime(socket, NetflixAction.FOCUS_EDITABLE)
            )
            await self._call(socket, "Input.insertText", {"text": text}, outcome_unknown_on_failure=True)
            if not submit:
                return focused
            submitted = await self._run_runtime(socket, NetflixAction.SUBMIT_PRIMARY)
            return self._accept_runtime_result(submitted)

        return await self._run_transaction(operation)
```

`_run_transaction(operation) -> NetflixContext` 使用 `self._port`，只在動作送出前的 target／connect／inject 暫時失敗最多重建一次；insertText、OK、SUBMIT_PRIMARY、BACK、PLAY_PAUSE 一旦 send 後 unknown 立即固定失敗，不重連。`_accept_runtime_result(result) -> NetflixContext` 的 top-level whitelist 增加且要求 `context`；先用 `NetflixContext.model_validate()` 驗證，再回傳 frozen model；ValidationError 只映射固定 `netflix_controller_unavailable`，不得 log raw result。

- [ ] **Step 6: 將 manager 完整遷移到規格簽章**

```python
# backend/app/applications/manager.py constructor order
self._netflix_debug_port = netflix_debug_port if netflix_debug_port is not None else reserve_localhost_port()
self._netflix_page = netflix_page or NetflixPageController(self._netflix_debug_port)

# inside existing open() after app validation
if app is ActiveApp.NETFLIX:
    await self._close_apps(ActiveApp.YOUTUBE, ActiveApp.NEWS)
    if self._focus_existing(ActiveApp.NETFLIX):
        return await self._initialize_netflix(reused=True)
    arguments = self._chrome_desktop_args(self._settings.urls.netflix, self._netflix_profile_dir)
    await self._launch_and_track(app, arguments, "Netflix")
    return await self._initialize_netflix(reused=False)

async def forward_command(self, command: Command) -> NetflixContext | None:
    self.require_input_target(self._active_app)
    if self._active_app is ActiveApp.NETFLIX:
        return await self._netflix_page.execute(command)
    if command is Command.BACK and self._active_app is ActiveApp.BROWSER:
        self._input.send_browser_back()
        return None
    self._input.send_command(command)
    return None

async def type_text(self, text: str, submit: bool = False) -> NetflixContext | None:
    self.require_input_target(self._active_app)
    if self._active_app is ActiveApp.NETFLIX:
        return await self._netflix_page.type_text(text, submit=submit)
    raise CommandExecutionError("input_target_not_active", "請先開啟 Netflix 再從遙控器輸入。")
```

`open()` 現有 YouTube／Browser 分支在各自成功路徑明確 `return None`。`_initialize_netflix(reused: bool) -> NetflixContext` 的既有 retry／rollback 外殼改呼叫 `self._netflix_page.initialize()` 並回傳其 context；不得用 TAB 代替 initialization，也不得把 `NetflixAction` 洩漏到 manager。更新 `FakeNetflixPageController` 為 `initialize() -> NetflixContext`、`execute(command: Command) -> NetflixContext` 與 `type_text(text: str, submit: bool = False) -> NetflixContext`。

- [ ] **Step 7: 執行 GREEN**

Run（repo root）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_netflix_page.py backend\tests\test_applications.py backend\tests\test_command_bus.py backend\tests\test_protocol_security.py
Push-Location frontend; npm test -- src/netflix/netflixControl.test.ts; npm run typecheck; Pop-Location
```

Expected: PASS；secret sentinel getter 未被觸發，socket closed，所有 side-effect unknown tests 的 connect 與 click／insert count 都為 1。

- [ ] **Step 8: Commit**

```bash
git add backend/app/applications/netflix_control.js backend/app/applications/netflix_page.py backend/app/applications/manager.py backend/tests/test_netflix_page.py backend/tests/test_applications.py frontend/src/netflix/netflixControl.test.ts
git commit -m "feat: synchronize Netflix page context"
```

---

### Task 6: PWA Inline Netflix Context Card

**Files:**
- Modify: `frontend/src/types/protocol.ts:27-40,83-88`
- Modify: `frontend/src/api/controllerSocket.ts:130-132`
- Modify: `frontend/src/api/controllerSocket.test.ts:150-175`
- Modify: `frontend/src/remote/RemotePage.tsx:158-370`
- Modify: `frontend/src/remote/RemotePage.test.tsx`
- Modify: `frontend/src/styles.css:231-263,356-360`

**Interfaces:**
- Consumes: backend JSON `netflix_context?: NetflixContext | null`、Task 4 exact enums、`sendText` return request id。
- Produces: PWA `NetflixStage`, `NetflixInputKind`, `NetflixContext`；`TextInputMessage.submit?: boolean`。
- Produces: `ControllerSocket.sendText(text: string, submit: boolean = false): string | null`。
- UI: context input submit 一律 `sendText(text, true)`；一般鍵盤維持 `sendText(text, false)`；null 立即 reset。

- [ ] **Step 1: 寫 socket serialization failing test**

```ts
// frontend/src/api/controllerSocket.test.ts
it('serializes optional submit without changing protocol version or message type', () => {
  const controller = connectedController()
  controller.sendText('secret', true)
  controller.sendText('plain')
  const messages = sentApplicationMessages()
  expect(messages.at(-2)).toMatchObject({ version: 1, type: 'text_input', text: 'secret', submit: true })
  expect(messages.at(-1)).toMatchObject({ version: 1, type: 'text_input', text: 'plain', submit: false })
})
```

- [ ] **Step 2: 寫 card mode、send-and-clear 與 null failing tests**

```tsx
// frontend/src/remote/RemotePage.test.tsx
it.each([
  ['email', 'email', '請輸入 Netflix 電子郵件或手機號碼'],
  ['password', 'password', '請輸入 Netflix 密碼'],
  ['code', 'text', '請輸入驗證碼 (OTP)'],
] as const)('renders safe %s context input', (input_kind, type, copy) => {
  renderConnectedRemote({
    netflix_context: { stage: input_kind === 'code' ? 'verification' : 'login', input_kind, has_error: false, can_submit: true, focused_title: null },
  })
  const input = screen.getByLabelText('Netflix 情境輸入')
  expect(input).toHaveAttribute('type', type)
  if (input_kind === 'code') expect(input).toHaveAttribute('inputmode', 'numeric')
  expect(screen.getByText(copy)).toBeInTheDocument()
})

it('submits once clears immediately waits for context and clears again on null', () => {
  const view = renderConnectedRemote({
    netflix_context: { stage: 'login', input_kind: 'password', has_error: false, can_submit: true, focused_title: null },
  })
  const input = screen.getByLabelText('Netflix 情境輸入')
  fireEvent.change(input, { target: { value: 'secret' } })
  fireEvent.click(screen.getByRole('button', { name: '送出 Netflix 輸入' }))
  expect(socketMock.sendText).toHaveBeenCalledTimes(1)
  expect(socketMock.sendText).toHaveBeenCalledWith('secret', true)
  expect(input).toHaveValue('')
  expect(screen.getByText('等待電視端回應...')).toBeInTheDocument()
  view.rerender(remoteWithState({ netflix_context: null }))
  expect(screen.queryByLabelText('Netflix 情境輸入')).not.toBeInTheDocument()
})
```

另用完整 test functions 驗證 generic error copy 恆為「登入或驗證失敗，請檢查電視畫面後重試」、browse 只顯示 `目前選取：{focused_title}`、details/watch 不顯示 title、context null 清空密碼、一般鍵盤呼叫 `sendText(text, false)`。

- [ ] **Step 3: 執行 RED**

Run（`frontend/`）：`npm test -- src/api/controllerSocket.test.ts src/remote/RemotePage.test.tsx`

Expected: FAIL；`sendText` 不接受第二參數，state type 與畫面沒有 `netflix_context`。

- [ ] **Step 4: 實作 TS types、socket 與 inline card state machine**

```ts
// frontend/src/types/protocol.ts
export type NetflixStage = 'login' | 'verification' | 'browse' | 'details' | 'watch' | 'unknown'
export type NetflixInputKind = 'email' | 'password' | 'code' | 'search' | 'none'
export interface NetflixContext {
  stage: NetflixStage
  input_kind: NetflixInputKind
  has_error: boolean
  can_submit: boolean
  focused_title: string | null
}
// ControllerState
netflix_context?: NetflixContext | null
// TextInputMessage
submit?: boolean
```

```ts
// frontend/src/api/controllerSocket.ts
sendText(text: string, submit = false): string | null {
  return this.sendRaw({
    version: PROTOCOL_VERSION,
    type: 'text_input',
    request_id: this.requestId(),
    text,
    submit,
  })
}
```

```tsx
// frontend/src/remote/RemotePage.tsx inside RemoteControl
const [netflixTyped, setNetflixTyped] = useState('')
const [waitingForNetflix, setWaitingForNetflix] = useState(false)
const netflixContext = state?.netflix_context ?? null

useEffect(() => {
  setNetflixTyped('')
  setWaitingForNetflix(false)
}, [netflixContext])

const submitNetflix = (event: FormEvent<HTMLFormElement>) => {
  event.preventDefault()
  if (controlsDisabled || netflixTyped.length === 0 || !netflixContext?.can_submit) return
  if (sendText(netflixTyped, true)) {
    setNetflixTyped('')
    setWaitingForNetflix(true)
  }
}
```

在 app buttons 後、D-Pad 前 render `<section className={has_error ? 'netflix-context-card is-error' : 'netflix-context-card'}>`。Email 用 `type="email"`，password 用 `type="password"`，code 用 `type="text" inputMode="numeric"`；三者均 `autoComplete="off"`, `autoCorrect="off"`, `spellCheck={false}`, `maxLength={256}`。Browse 只顯示安全 title 與既有 OK 提示。null 不 render；error 不拼接 server／Netflix 原始文字。一般鍵盤明確改為 `sendText(typed, false)`。

- [ ] **Step 5: 加入既有視覺系統樣式**

```css
.netflix-context-card {
  margin: 1rem 0;
  padding: 1rem;
  border: 1px solid #43516a;
  border-radius: 1rem;
  background: #141d2b;
}
.netflix-context-card.is-error { border-color: #e50914; }
.netflix-context-card form { display: grid; grid-template-columns: 1fr auto; gap: .65rem; }
.netflix-context-card input { min-width: 0; min-height: 3.5rem; }
.netflix-context-waiting { color: #cbd6e4; }
```

- [ ] **Step 6: 執行 GREEN**

Run（`frontend/`）：`npm test -- src/api/controllerSocket.test.ts src/remote/RemotePage.test.tsx && npm run typecheck`

Expected: PASS；password DOM input 在 send 後 value 立即為空，null 後卡片不存在。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/protocol.ts frontend/src/api/controllerSocket.ts frontend/src/api/controllerSocket.test.ts frontend/src/remote/RemotePage.tsx frontend/src/remote/RemotePage.test.tsx frontend/src/styles.css
git commit -m "feat: show Netflix context in PWA remote"
```

---

### Task 7: Expo Inline Netflix Context Card and TAB Control

**Files:**
- Modify: `mobile/src/types/protocol.ts:3-39,82-87`
- Modify: `mobile/src/api/controllerSocket.ts:113-122`
- Modify: `mobile/src/api/controllerSocket.test.ts:515-540`
- Modify: `mobile/src/components/TextInputModal.tsx:15-88`
- Modify: `mobile/src/screens/RemoteScreen.tsx:17-330`
- Modify: `mobile/src/screens/RemoteScreen.test.tsx`

**Interfaces:**
- Consumes: Task 4 exact context JSON；Task 6 相同 copy、modes、submit 與 clear semantics。
- Produces: Expo `NetflixStage`, `NetflixInputKind`, `NetflixContext` 與 `Command` 中的 `'TAB'`。
- Produces: `ControllerSocket.sendTextInput(text: string, submit: boolean = false): Promise<Acknowledgement>`。
- Produces: `TextInputModal.onSend(text: string, submit: boolean): Promise<void>` 與 `inputKind: NetflixInputKind`；manual modal 傳 false，context card 傳 true。

- [ ] **Step 1: 寫 socket 與 TAB failing tests**

```ts
// mobile/src/api/controllerSocket.test.ts
it('serializes submit on version one text_input and keeps false default', async () => {
  const socket = connectedSocket()
  const submitted = socket.sendTextInput('secret', true)
  const plain = socket.sendTextInput('plain')
  const messages = applicationMessages()
  expect(messages.at(-2)).toMatchObject({ version: 1, type: 'text_input', text: 'secret', submit: true })
  expect(messages.at(-1)).toMatchObject({ version: 1, type: 'text_input', text: 'plain', submit: false })
  acknowledgeLatestTwo()
  await Promise.all([submitted, plain])
})
```

```tsx
// mobile/src/screens/RemoteScreen.test.tsx
it('sends TAB from the native toolbar', async () => {
  renderRemote()
  const tab = root.findByProps({ accessibilityLabel: '下一欄' })
  await act(async () => tab.props.onPress())
  expect(latestMockSocket!.sendCommand).toHaveBeenCalledWith('TAB')
})
```

- [ ] **Step 2: 寫 Expo modes、submit、immediate clear 與 null failing tests**

```tsx
// mobile/src/screens/RemoteScreen.test.tsx
it.each([
  ['email', 'email-address', false],
  ['password', 'default', true],
  ['code', 'number-pad', false],
] as const)('renders %s context with safe native input mode', (input_kind, keyboardType, secureTextEntry) => {
  renderRemoteWithContext({
    stage: input_kind === 'code' ? 'verification' : 'login',
    input_kind,
    has_error: false,
    can_submit: true,
    focused_title: null,
  })
  const input = root.findByProps({ accessibilityLabel: 'Netflix 情境輸入' })
  expect(input.props.keyboardType).toBe(keyboardType)
  expect(input.props.secureTextEntry).toBe(secureTextEntry)
  expect(input.props.autoCapitalize).toBe('none')
  expect(input.props.autoCorrect).toBe(false)
})

it('sends context text once with submit true and clears before ack', async () => {
  renderRemoteWithContext({ stage: 'login', input_kind: 'password', has_error: false, can_submit: true, focused_title: null })
  const input = root.findByProps({ accessibilityLabel: 'Netflix 情境輸入' })
  act(() => input.props.onChangeText('secret'))
  const deferred = deferredAcknowledgement()
  latestMockSocket!.sendTextInput.mockReturnValueOnce(deferred.promise)
  act(() => root.findByProps({ accessibilityLabel: '送出 Netflix 輸入' }).props.onPress())
  expect(latestMockSocket!.sendTextInput).toHaveBeenCalledWith('secret', true)
  expect(root.findByProps({ accessibilityLabel: 'Netflix 情境輸入' }).props.value).toBe('')
  expect(root.findByProps({ accessibilityLabel: '等待電視端回應' })).toBeTruthy()
  deferred.resolve(mockAck())
})
```

另以 state callback 發 `netflix_context: null` 後 assert card 不存在、local text 空；browse 顯示 title 與 OK；has_error 只顯示固定 generic copy；manual `TextInputModal` 呼叫 `sendTextInput(text, false)`。

- [ ] **Step 3: 執行 RED**

Run（`mobile/`）：`npm test -- --runInBand src/api/controllerSocket.test.ts src/screens/RemoteScreen.test.tsx`

Expected: FAIL；`TAB` 不在 mobile `Command`，socket 無第二參數，畫面沒有 context card。

- [ ] **Step 4: 實作 mobile types、socket 與 modal 簽章**

```ts
// mobile/src/types/protocol.ts
export type NetflixStage = 'login' | 'verification' | 'browse' | 'details' | 'watch' | 'unknown'
export type NetflixInputKind = 'email' | 'password' | 'code' | 'search' | 'none'
export interface NetflixContext {
  stage: NetflixStage
  input_kind: NetflixInputKind
  has_error: boolean
  can_submit: boolean
  focused_title: string | null
}
// Command union 加：
| 'TAB'
// ControllerState 加：
netflix_context?: NetflixContext | null
// TextInputMessage 加：
submit?: boolean
```

```ts
// mobile/src/api/controllerSocket.ts
public sendTextInput(text: string, submit = false): Promise<Acknowledgement> {
  const requestId = this.generateRequestId()
  const message: ClientMessage = {
    version: 1,
    type: 'text_input',
    request_id: requestId,
    text,
    submit,
  }
  return this.sendWithAcknowledgement(message)
}
```

`TextInputModalProps` 改為 `inputKind: NetflixInputKind` 與 `onSend(text: string, submit: boolean): Promise<void>`；`keyboardType` 映射 email/password/code，password 使用 `secureTextEntry`，modal 的一般送出固定 `await onSend(text, false)` 並在呼叫後立即 `setText('')`，不等待 ack 才清 secret。

- [ ] **Step 5: 實作 RemoteScreen inline card、TAB 與等待狀態**

```tsx
// mobile/src/screens/RemoteScreen.tsx state and sender
const [netflixText, setNetflixText] = useState('')
const [waitingForNetflix, setWaitingForNetflix] = useState(false)
const netflixContext = controllerState?.netflix_context ?? null

useEffect(() => {
  setNetflixText('')
  setWaitingForNetflix(false)
}, [netflixContext])

const handleNetflixSubmit = async (): Promise<void> => {
  if (!socket || !netflixContext?.can_submit || netflixText.length === 0) return
  const text = netflixText
  setNetflixText('')
  setWaitingForNetflix(true)
  const ack = await socket.sendTextInput(text, true)
  if (!ack.success) setErrorMessage(ack.message || ack.error_code || '無法送出文字')
}
```

在 app launcher 與 D-Pad 之間 render `View accessibilityLabel="Netflix 情境卡"`。使用 `TextInput accessibilityLabel="Netflix 情境輸入"`，email `keyboardType="email-address"`，password `secureTextEntry`, code `keyboardType="number-pad"`，三者 `autoCapitalize="none"`, `autoCorrect={false}`, `maxLength={256}`。加入 `TouchableOpacity accessibilityLabel="下一欄"` 呼叫 `handleCommand('TAB')`。Context null 不 render並 reset；等待狀態由下一筆 context callback解除，不把 ack message 當頁面狀態。

- [ ] **Step 6: 執行 GREEN**

Run（`mobile/`）：`npm test -- --runInBand src/api/controllerSocket.test.ts src/screens/RemoteScreen.test.tsx && npm run typecheck`

Expected: PASS；PWA／Expo 的 copy 與 submit payload 相同，Expo password 在 unresolved ack 前已清空。

- [ ] **Step 7: Commit**

```bash
git add mobile/src/types/protocol.ts mobile/src/api/controllerSocket.ts mobile/src/api/controllerSocket.test.ts mobile/src/components/TextInputModal.tsx mobile/src/screens/RemoteScreen.tsx mobile/src/screens/RemoteScreen.test.tsx
git commit -m "feat: show Netflix context in Expo remote"
```

---

### Task 8: Documentation, Full Gates, Production Restart, and Real Devices

**Files:**
- Modify: `README.md:124-133`
- Modify: `docs/ARCHITECTURE.md:5-69`
- Modify: `docs/PROTOCOL.md:71-136,183-190`
- Modify: `docs/WINDOWS_SETUP.md:19-50`
- Verify: all files in the File Map

**Interfaces:**
- Consumes: Tasks 1–7 exact flags、standalone app shell、controller lifecycle、context schema、port return types、wire fields、PWA／Expo UX。
- Produces: user／operator documentation with no Edge-era Netflix claim, no credential-storage implication, and explicit external prerequisites for credentialed smoke tests。
- Produces: one final evidence set covering backend、frontend、mobile、Pester、production restart and real Chrome／PWA／Expo。

- [ ] **Step 1: 執行 documentation RED gate**

Run（repo root）：

```powershell
$required = 'disable-notifications|deny-permission-prompts|YoutubeFullscreenController|netflix_context|submit'
$hits = Select-String -Path README.md,docs\ARCHITECTURE.md,docs\PROTOCOL.md,docs\WINDOWS_SETUP.md -Pattern $required
if ($hits.Count -ge 10) { exit 0 } else { exit 1 }
```

Expected: exit `1`；目前文件尚未完整描述五個契約。

- [ ] **Step 2: 更新四份文件的精確內容**

`README.md` 明列 TV 專用 Chrome 兩旗標、Netflix `--app=<url>` 獨立視窗（無 tab / omnibox / browser chrome）、YouTube 每影片一次且 Esc 不拉回、Netflix safe context、PWA／Expo inline card、Expo TAB、credentials 不保存。`docs/ARCHITECTURE.md` Mermaid 加入 `Netflix standalone app window (Chrome --app=<url>)` 與 `YoutubeFullscreenController` bounded probe 與 `NetflixPageController -> NetflixContext -> CommandBus -> StateStore -> PWA/Expo`，文字明定 CommandBus sole owner、short socket、bounded settle與 null invalidation。`docs/PROTOCOL.md` 加入以下 version 1 JSON，並說明欄位 optional：

```json
{
  "version": 1,
  "type": "text_input",
  "request_id": "text-45",
  "text": "user supplied text",
  "submit": true
}
```

```json
{
  "version": 1,
  "type": "state",
  "active_app": "netflix",
  "focused_tile": "netflix",
  "volume": 50,
  "muted": false,
  "channel_number": null,
  "channel_name": null,
  "status_message": null,
  "error_message": null,
  "netflix_context": {
    "stage": "login",
    "input_kind": "email",
    "has_error": false,
    "can_submit": true,
    "focused_title": null
  }
}
```

`docs/WINDOWS_SETUP.md` 更正 Chrome/profile 行為與 Netflix `--app` 獨立視窗，列出 production restart、notification site、YouTube Esc、PWA＋Expo Netflix 驗收；明確寫「credentialed browse／direct-play 需要由操作者在 repo、log 與螢幕錄影之外安全提供可用測試帳號及 OTP 收取方式；未提供時結果標記為 external prerequisite blocked，不得記為通過」；明確說明不測/不做 Store PWA / WebView / Electron / APK。

- [ ] **Step 3: 執行 documentation GREEN gate**

Run（repo root）：

```powershell
Select-String -Path README.md,docs\ARCHITECTURE.md,docs\PROTOCOL.md,docs\WINDOWS_SETUP.md -Pattern 'disable-notifications|deny-permission-prompts|YoutubeFullscreenController|netflix_context|submit|external prerequisite'
if (Select-String -Path README.md,docs\ARCHITECTURE.md,docs\PROTOCOL.md,docs\WINDOWS_SETUP.md -Pattern 'Netflix.*Edge|Edge.*Netflix|store.*password|password.*log') { exit 1 }
```

Expected: 第一個命令四份文件都有命中；第二個命令 exit `0` 且無輸出。

- [ ] **Step 4: 執行 backend full、Ruff、integration smoke、frontend、mobile 與 Pester full gates**

Run（repo root）：

```powershell
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests
.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_integration_smoke.py
Push-Location frontend; npm run lint; npm run build; npm test; Pop-Location
Push-Location mobile; npm run typecheck; npm test -- --runInBand; Pop-Location
Invoke-Pester -Path .\scripts\tests\startup.Tests.ps1
```

Expected: Ruff lint、backend full pytest、integration smoke、frontend lint/build/test、mobile typecheck/test、Pester startup 全部 PASS；沒有 pending asyncio task、React act warning、package／lockfile diff 或 Pester startup regression。
- [ ] **Step 5: 執行安全、型別與 clean-cutover gates**

Run（repo root）：

```powershell
$forbidden = 'input\.value|\.value\.length|Network\.|Storage\.|getCookies|MediaKey|--remote-debugging-address=0\.0\.0\.0'
if (Select-String -Path backend\app\applications\youtube_fullscreen.py,backend\app\applications\netflix_page.py,backend\app\applications\netflix_control.js -Pattern $forbidden) { exit 1 }
Select-String -Path backend\app\protocol.py,backend\app\commands\ports.py,backend\app\applications\netflix_page.py,frontend\src\types\protocol.ts,mobile\src\types\protocol.ts -Pattern 'NetflixContext|NetflixStage|NetflixInputKind|submit'
git diff --check
```

Expected: forbidden scan exit `0`；五個檔案的型別／submit 命中；`git diff --check` 無輸出。

- [ ] **Step 6: Production restart 後驗收真實 notification popup、Netflix standalone 視窗與 YouTube fullscreen**

Run（repo root）：`.\scripts\start.ps1 -NoTunnel`

Expected: 非 reload production controller restart 成功、health ready、TV launcher 開啟。用 manager-owned `config/chrome-tv-profile` 與 `config/chrome-netflix-profile` 實例造訪真實 notification／permission 測試頁（例如 `https://permission.site/`），點擊請求 Notification 與 Location；TV 不出現 Chrome permission popup，且日常 Chrome profile 不變。Netflix 視窗以獨立面板（--app）開啟，無分頁列、網址列與一般瀏覽器外框，全螢幕與 Widevine 正常；開任一 YouTube watch／TV hash／shorts／live 影片，video ready 後 1 秒內只送一次 fullscreen；按 Esc 後等待至少三個 probe interval，同一 video 不再 fullscreen；切下一影片才可再觸發。

- [ ] **Step 7: 以 PWA 與 Expo 驗收 Netflix 登入 context、清空與零回讀**

前置：安全提供未登入測試帳號與 OTP 收取方式，不把值貼入 issue、commit、console、log、screenshot 或 state capture。依序確認 email card、password secure card、code card；每次 submit 只發一次且 client field 立即清空；錯誤只顯示 generic copy；HOME、切 YouTube、關閉 Netflix 後兩端 card 與 local text 立即消失。檢查 production log、WebSocket state／ack 與 browser CDP response，均無輸入值、長度、Cookie、Token 或 Session Secret；每個動作後 CDP socket 關閉。

若安全帳號／OTP 前置不可用，將此步結果記為 `BLOCKED — external prerequisite: safe Netflix test credentials and OTP channel unavailable`，不得以 fixture、個人帳號猜測或未觀察結果替代 PASS。

- [ ] **Step 8: 以 credentialed browse 驗收 rail、TAB、OK direct-play 與 BACK／PLAY_PAUSE**

在 PWA 與 Expo 各自操作：TAB 切 Profile／非標準彈窗焦點；NAV_LEFT／RIGHT 僅在 active rail；NAV_UP／DOWN 到相鄰 rail 最接近 X 的 card；兩端顯示相同且最長 120 字的 focused title。選一張無直接 Play 的 card 按 OK，只 click card 一次並在 1200ms 內 click detail Play 一次；選一張有 Play／Resume 的 card 只直接 click 一次；timeout／斷 CDP 不重送。進 watch 後 PLAY_PAUSE 只控制目前 Netflix video，BACK 回 browse；details BACK 只關 overlay。HOME 清 context。

若沒有安全可用的 credentialed Netflix 測試帳號，將此步記為 `BLOCKED — external prerequisite: credentialed Netflix browse account unavailable`，不得聲稱 rail、direct-play 或 Widevine 已驗收。

- [ ] **Step 9: Commit documentation**

```bash
git add README.md docs/ARCHITECTURE.md docs/PROTOCOL.md docs/WINDOWS_SETUP.md
git commit -m "docs: document TV playback and Netflix sync"
```

---

## Final Evidence Gate

- [ ] 八個 task 的 Conventional Commit 都存在，且每個 commit 只含該 task File Map 所列檔案。
- [ ] 真實 Netflix 視窗以獨立應用程式面板（--app）開啟，無分頁列、網址列與外框，CDP 埠與 Widevine 播放正常，不依賴 Store PWA／WebView／Electron／APK。
- [ ] Backend full pytest、Ruff lint、integration smoke、frontend lint/build/test、mobile typecheck/test、Pester startup 皆有本次執行的 PASS output。
- [ ] Production controller 已以 `scripts/start.ps1` restart，health ready，不是 dev reload process。
- [ ] 真實 notification／location prompt 請求被兩種 TV 專用 Chrome argv 阻擋，個人 Chrome profile／registry 未變。
- [ ] 任一真實 YouTube 影片自動 fullscreen；同影片 Esc 後至少三秒不拉回；下一影片才再觸發。
- [ ] 未登入 Netflix 的 email／password／code context 在 PWA 與 Expo 同步，password 安全遮蔽，submit 後立即清空。
- [ ] Credentialed browse 的 rail、focused title、Expo TAB、OK direct-play、BACK、PLAY_PAUSE 兩端一致；缺安全帳密時保留 external prerequisite blocked 證據而非 PASS。
- [ ] 每個 YouTube probe 與 Netflix action 都是 localhost short CDP；unknown outcome 無 replay；state／ack／error／log 無 credential 值或長度。
- [ ] `netflix_context: null` 在 HOME、切 app、close／crash 後卸載兩端 card 並清本地 input。
- [ ] `git diff --check` 無輸出，package／lockfile 無變更，`.serena/`、`.superpowers/` 與 Chrome profiles 無變更，無新增任何外部依賴。
## Author Self-Review (Completed)

- [x] Spec coverage：Task 1 覆蓋 notification；Task 2 覆蓋 Netflix standalone app shell；Task 3 覆蓋 YouTube；Task 4 覆蓋 protocol/state/ports/bus；Task 5 覆蓋 runtime、rail、direct-play、type+submit、BACK／PLAY_PAUSE；Tasks 6–7 覆蓋 PWA／Expo；Task 8 與 Final Gate 覆蓋 docs、全套與實機。
- [x] Placeholder scan：每個 RED 都有具名可執行 test code、命令與預期失敗；每個 implementation step 都有固定簽章、code 或逐分支行為；沒有延後實作或跨 task 代稱。
- [x] Type consistency：全文件只使用 `NetflixContext`, `NetflixStage`, `NetflixInputKind`；`TextInputMessage.submit` 預設 false；page controller 回傳非 optional context，ApplicationPort／manager 回傳 optional context；PWA／Expo 欄位完全同名。
- [x] Lifecycle consistency：`YoutubeFullscreenController.start(port)`, `stop()`, `probe_once(port)` 在 tests、manager、docs 完全一致；Netflix context 只有 CommandBus 寫 StateStore。
- [x] Safety consistency：at-most-once、short CDP、零回讀、context null、雙 client send-and-clear 與外部帳密前置都有自動或實機 gate。
- [x] Dependency consistency：沒有新 dependency、wire type、protocol version、DRM interception、generic automation、watch URL 拼裝或 fallback。
