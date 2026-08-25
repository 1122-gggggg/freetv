# Netflix TV Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Windows 11 PC TV Box 上，讓 `/remote` PWA 與 `mobile/` Expo 原生手機遙控器沿用現有協定，透過 localhost CDP 完成 Netflix 登入、選人、瀏覽、搜尋、詳情、播放、返回與 HOME 的全程免滑鼠操作。

**Architecture:** 保留 `Remote WebSocket → CommandBus → ApplicationManager` 單一路徑；Netflix 的 NAV／OK／BACK／PLAY_PAUSE／TAB／文字改由 `NetflixPageController` 以每指令短 CDP 連線驅動固定版本的 `netflix_control.js`，不再進入 Windows `SendInput`／`Alt+Left`。DOM runtime 每次動作重新列舉可見互動元素，回傳不含輸入值的語意焦點；`HOME` 仍完全使用既有 ownership 行為。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic 2、httpx、websockets、pytest、JavaScript DOM runtime、React 19／TypeScript 5.9、Vite 7／Vitest 4／jsdom 27、Expo 57／React Native 0.86／Jest 29、Windows 11 Chrome／Widevine。

## Global Constraints

- 只控制 `ApplicationManager` 追蹤之專用 Chrome 中唯一、top-level、host 為 `netflix.com` 或其子網域的 page target。
- CDP 僅使用 `127.0.0.1`；每個頁面指令使用短連線，動作完成即關閉，不建立常駐 CDP 事件監聽器。
- 每次動作重新列舉當下 DOM；document／execution context 失效後由下一指令重選 target、確認版本並重注入。
- CDP 連線、target 查詢或 runtime 注入的暫時性失敗只重試一次完整短連線流程；確定性 DOM／target 錯誤不重試。
- iframe、帶 `openerId` 的 popup、多個可接受 Netflix page target 或非 Netflix target 不得 fallback 至其他 page、分頁、視窗或 Windows 輸入。
- Netflix 的 `NAV_UP`、`NAV_DOWN`、`NAV_LEFT`、`NAV_RIGHT`、`OK`、`BACK`、`PLAY_PAUSE`、`TAB` 與 `text_input` 只走頁面控制器，禁止雙重觸發；`HOME` 不進 DOM，維持既有 ownership。
- `/remote` PWA 與 `mobile/` Expo 共用現有 protocol version 1、`CommandMessage`、`TextInputMessage` 與 acknowledgement；不新增 wire message、不變更 command 字串。
- `text_input` 維持 1–256 個經 `sanitize_text` 清理的可見 Unicode 字元；不得讀回、記錄或回傳帳號、密碼、驗證碼及輸入欄 value。
- 保留 `config/chrome-netflix-profile`、`--start-fullscreen`、Chrome Widevine、登入狀態與真正全螢幕；不載入 AdBlock。
- 不修改 Netflix 請求、回應、Cookie、Service Worker、MediaKey、Widevine、授權交換或 DRM。
- 不新增 npm／Python 依賴；DOM fixture 測試使用前端現有 Vitest＋jsdom。
- 不修改 protocol unions、PWA UI 或 Expo UI；只新增其既有協定與控制面的回歸測試。
- 不加入、修改或刪除 `.serena/`、`.superpowers/`、`config/chrome-netflix-profile/` 或其他使用者檔案。

## File Map

| 狀態 | 檔案 | 單一責任 |
|---|---|---|
| Create | `backend/app/applications/netflix_control.js` | 版本 `1` 的固定 DOM runtime、二維焦點、語意恢復、OK／BACK／PLAY_PAUSE／輸入聚焦。 |
| Create | `backend/app/applications/netflix_page.py` | localhost page discovery、唯一 target 驗證、短 CDP transaction、一次重試、runtime 注入與固定錯誤。 |
| Delete | `backend/app/applications/chrome_page.py` | 移除只處理登入欄且會 fallback target 的舊 `ChromePageInput`。 |
| Modify | `backend/app/applications/manager.py` | 注入 `NetflixPageController`，Netflix clean cutover，保留 Chrome profile／全螢幕／ownership。 |
| Modify | `backend/app/config.py` | 將 `urls.netflix` 限制為 HTTPS `netflix.com` 或子網域。 |
| Verify unchanged | `backend/app/commands/ports.py` | 現有 `ApplicationPort.forward_command(Command)`、`type_text(str)` 已是所需窄介面。 |
| Verify unchanged | `backend/app/commands/bus.py` | 現有序列化 dispatch 與 `ApplicationPort` 呼叫已是單一路徑；用測試鎖定 Netflix 路由與 HOME。 |
| Create | `backend/tests/test_netflix_page.py` | target、短連線、版本注入、重試、固定錯誤、文字保密的 controller 契約。 |
| Delete | `backend/tests/test_chrome_page.py` | 移除允許 fallback 到任意 page 的舊測試。 |
| Modify | `backend/tests/test_applications.py` | manager 路由、無 SendInput／Alt+Left、HOME ownership、啟動參數。 |
| Modify | `backend/tests/test_command_bus.py` | Netflix 命令／文字／錯誤 ack／HOME 的 ApplicationPort 路由回歸。 |
| Modify | `backend/tests/test_config.py` | Netflix HTTPS host 限制。 |
| Modify | `backend/tests/test_protocol_security.py` | 固定 version 1、256 字與禁止額外 wire payload 的回歸。 |
| Create | `frontend/src/netflix/netflixControl.test.ts` | 以 jsdom fixture 載入真實 backend runtime，驗證 DOM 行為。 |
| Modify | `frontend/src/remote/RemotePage.test.tsx` | PWA 四方向、OK、BACK、PLAY_PAUSE、文字與現有 wire 能力回歸。 |
| Modify | `frontend/src/api/controllerSocket.test.ts` | PWA command／text 序列化仍為既有兩種 message。 |
| Modify | `mobile/src/screens/RemoteScreen.test.tsx` | Expo 控制面、失敗 ack 與文字回歸。 |
| Modify | `mobile/src/api/controllerSocket.test.ts` | Expo command／text 序列化與 256 字契約回歸。 |
| Modify | `README.md` | 把 Netflix／Edge 舊敘述改為專用 Chrome、Widevine、localhost CDP 與兩種手機遙控器。 |
| Modify | `docs/ARCHITECTURE.md` | 加入 page adapter、短連線資料流、clean cutover 與 HOME ownership。 |
| Verify unchanged | `backend/app/protocol.py`、`frontend/src/types/protocol.ts`、`mobile/src/types/protocol.ts` | protocol version 1 與現有 message／command 名稱不變。 |

---

### Task 1: Versioned Netflix DOM Runtime and Fixture Contracts

**Files:**
- Create: `backend/app/applications/netflix_control.js`
- Create: `frontend/src/netflix/netflixControl.test.ts`

**Interfaces:**
- Consumes: DOM APIs、`HTMLElement.getBoundingClientRect()`、`document.elementFromPoint()`、`history.back()`、目前 document 的可見 `HTMLVideoElement`。
- Produces: `globalThis.__freeTvNetflixControl.version === "1"`。
- Produces: `globalThis.__freeTvNetflixControl.run(action: NetflixRuntimeAction, previousFocus: FocusFingerprint | null): RuntimeResult`。
- `NetflixRuntimeAction` 固定為 `"FOCUS_PRIMARY" | "FOCUS_EDITABLE" | "FOCUS_NEXT" | "NAV_UP" | "NAV_DOWN" | "NAV_LEFT" | "NAV_RIGHT" | "OK" | "BACK" | "PLAY_PAUSE"`。
- `FocusFingerprint` 固定為 `{ role: string; label: string; uia: string; text: string; pathKind: string; rail: string; index: number }`；不得包含 `value`、`innerHTML` 或輸入內容。
- `RuntimeResult` 固定為 `{ ok: boolean; status: string; code?: "netflix_focus_unavailable" | "netflix_input_unavailable" | "netflix_video_unavailable"; focus?: FocusFingerprint }`。

- [ ] **Step 1: 建立 fixture harness 與可觀察 failing tests**

`frontend/src/netflix/netflixControl.test.ts` 必須讀取實際 runtime，不得複製 production code：

```ts
import { readFileSync } from 'node:fs'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const runtimeSource = readFileSync(
  new URL('../../../backend/app/applications/netflix_control.js', import.meta.url),
  'utf8',
)

type RuntimeResult = { ok: boolean; status: string; code?: string; focus?: Record<string, string | number> }
type Runtime = { version: string; run: (action: string, focus: Record<string, string | number> | null) => RuntimeResult }

function runtime(): Runtime {
  return (globalThis as typeof globalThis & { __freeTvNetflixControl: Runtime }).__freeTvNetflixControl
}

function setRect(element: Element, left: number, top: number, width = 120, height = 60): void {
  Object.defineProperty(element, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({ left, top, right: left + width, bottom: top + height, width, height, x: left, y: top, toJSON: () => ({}) }),
  })
}

beforeEach(() => {
  document.body.innerHTML = ''
  window.eval(runtimeSource)
})

it('moves right by rectangles and keeps focus at the boundary', () => {
  document.body.innerHTML = '<button id="a">A</button><button id="b">B</button><button id="c">C</button>'
  const [a, b, c] = [...document.querySelectorAll('button')]
  setRect(a, 0, 0); setRect(b, 180, 0); setRect(c, 180, 140)
  a.focus()
  expect(runtime().run('NAV_RIGHT', null).status).toBe('moved')
  expect(document.activeElement).toBe(b)
  expect(runtime().run('NAV_RIGHT', null).status).toBe('boundary')
  expect(document.activeElement).toBe(b)
})
```

同檔加入具名 fixture tests：

- `filters hidden disabled zero-area offscreen and covered candidates`
- `prefers axis overlap then primary distance then perpendicular distance then DOM order`
- `restores a rebuilt card by role label data-uia path rail and index`
- `falls back to the page primary action when the previous semantic target disappeared`
- `focuses editable fields without reading value`
- `clicks cards and buttons but only focuses input on OK`
- `closes the top dialog or detail layer before history back`
- `toggles only the visible video in the current document`
- `returns stable focus input and video error codes`
- `adds white outline red glow and center-center scrollIntoView`

- [ ] **Step 2: 執行 fixture tests，確認先失敗**

Run（`frontend/`）：`npm test -- src/netflix/netflixControl.test.ts`

Expected: FAIL，`ENOENT` 指向 `backend/app/applications/netflix_control.js`。

- [ ] **Step 3: 實作最小固定 runtime**

```js
(() => {
  const VERSION = '1'
  const ACTIONS = new Set([
    'FOCUS_PRIMARY', 'FOCUS_EDITABLE', 'FOCUS_NEXT',
    'NAV_UP', 'NAV_DOWN', 'NAV_LEFT', 'NAV_RIGHT',
    'OK', 'BACK', 'PLAY_PAUSE',
  ])
  const interactiveElements = () => [...document.querySelectorAll(
    'a[href],button,input,textarea,[tabindex]:not([tabindex="-1"]),[role="button"],[data-uia]'
  )].filter((element) => element instanceof HTMLElement && !element.matches(':disabled,[aria-disabled="true"]'))
  const run = (action, previousFocus = null) => {
    if (!ACTIONS.has(action)) return { ok: false, status: 'error', code: 'netflix_focus_unavailable' }
    const elements = interactiveElements()
    if (action === 'FOCUS_PRIMARY') {
      const target = elements[0]
      if (!target) return { ok: false, status: 'error', code: 'netflix_focus_unavailable' }
      target.focus({ preventScroll: true })
      target.style.outline = '3px solid #fff'
      target.style.boxShadow = '0 0 0 3px #fff, 0 0 18px 6px rgba(229,9,20,.95)'
      target.scrollIntoView({ block: 'center', inline: 'center' })
      return { ok: true, status: previousFocus ? 'restored' : 'focused' }
    }
    return { ok: false, status: 'error', code: 'netflix_focus_unavailable' }
  }
  globalThis.__freeTvNetflixControl = { version: VERSION, run }
})()
```

以上 code block 固定 global name、version、actions、result shape 與無候選行為；同一步完成所有 fixture 所要求的分支：

1. `visible()` 排除 hidden、disabled、零面積、視窗外與中心點被覆蓋元素。
2. 方向搜尋只保留目標半平面；主軸投影重疊優先，再比較主方向距離、垂直距離與當次 DOM index。
3. 有有效焦點但無方向候選回 `boundary`；無有效焦點先以 `previousFocus` 語意恢復，失敗才選主要操作。
4. `fingerprint()` 只讀七個白名單欄位，input／textarea 絕不讀 `.value`。
5. `OK` 對輸入欄只 focus，對其餘可點擊項目呼叫原生 `click()`。
6. `BACK` 先關最上層可見 dialog／detail overlay，沒有才 `history.back()`。
7. `PLAY_PAUSE` 只對目前 document 的第一個可見 video 呼叫 `play()`／`pause()`。
8. 每次 `run()` 重新呼叫 `interactiveElements()`；不得把 Element、Node、矩形保存到下一次。

- [ ] **Step 4: 執行 fixture tests與前端靜態檢查**

Run（`frontend/`）：`npm test -- src/netflix/netflixControl.test.ts && npm run lint && npm run typecheck`

Expected: PASS；`frontend/package.json` 與 lockfile 無變更。

- [ ] **Step 5: Commit**

```bash
git add backend/app/applications/netflix_control.js frontend/src/netflix/netflixControl.test.ts
git commit -m "feat: add Netflix DOM control runtime"
```

---

### Task 2: Short-Lived Netflix Page Controller

**Files:**
- Create: `backend/app/applications/netflix_page.py`
- Create: `backend/tests/test_netflix_page.py`

**Interfaces:**
- Consumes: `CommandExecutionError(code: str, message: str)`、`httpx.AsyncClient`、`websockets.connect`、Task 1 runtime version `"1"` 與 `run()`。
- Produces: `NetflixAction(StrEnum)`，值與 Task 1 `NetflixRuntimeAction` 完全相同。
- Produces: `FocusFingerprint = dict[str, str | int]`。
- Produces: `select_netflix_target(pages: list[dict[str, Any]]) -> str`。
- Produces: `NetflixPageController(timeout: float = 8.0, runtime_path: Path | None = None)`。
- Produces: `execute(port: int, action: NetflixAction) -> None`、`type_text(port: int, text: str) -> None`。
- Private methods固定為 `_run_transaction`、`_list_pages`、`_run_runtime`、`_accept_runtime_result`、`_call`；後續 task 不直接呼叫。

- [ ] **Step 1: 先寫 target 與短 transaction failing tests**

```python
import pytest
from app.applications.netflix_page import NetflixAction, NetflixPageController, select_netflix_target
from app.commands.ports import CommandExecutionError


def test_select_netflix_target_requires_one_top_level_netflix_page() -> None:
    assert select_netflix_target([
        {"type": "page", "url": "chrome://newtab", "webSocketDebuggerUrl": "ws://127.0.0.1/new"},
        {"type": "page", "url": "https://www.netflix.com/browse", "webSocketDebuggerUrl": "ws://127.0.0.1/netflix"},
    ]) == "ws://127.0.0.1/netflix"


@pytest.mark.parametrize("pages", [
    [{"type": "iframe", "url": "https://www.netflix.com/login", "webSocketDebuggerUrl": "ws://127.0.0.1/frame"}],
    [{"type": "page", "openerId": "main", "url": "https://www.netflix.com/verify", "webSocketDebuggerUrl": "ws://127.0.0.1/popup"}],
])
def test_select_netflix_target_rejects_non_top_level_targets(pages: list[dict[str, str]]) -> None:
    with pytest.raises(CommandExecutionError) as caught:
        select_netflix_target(pages)
    assert caught.value.code == "netflix_target_unsupported"
```

以記錄 send／recv／closed 的 `FakeSocket` 及 monkeypatch 加入：

- `test_execute_opens_one_socket_checks_version_runs_action_and_closes`
- `test_execute_injects_runtime_only_when_version_is_missing`
- `test_execute_retries_connection_once_then_returns_page_unavailable`
- `test_execute_retries_injection_once_then_returns_controller_unavailable`
- `test_multiple_top_level_targets_return_unsupported_without_retry`
- `test_next_command_reinjects_after_execution_context_replacement`
- `test_each_action_sends_previous_focus_without_element_references`
- `test_type_text_focuses_editable_then_uses_input_insert_text`
- `test_type_text_does_not_log_or_return_secret`
- `test_runtime_codes_map_to_fixed_local_chinese_messages`

- [ ] **Step 2: 執行 controller tests，確認先失敗**

Run（repo root）：`.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_netflix_page.py`

Expected: FAIL during collection with `ModuleNotFoundError: app.applications.netflix_page`。

- [ ] **Step 3: 實作 actions、唯一 target 與固定錯誤**

```python
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse
from app.commands.ports import CommandExecutionError

RUNTIME_VERSION = "1"
ERROR_MESSAGES = {
    "netflix_page_unavailable": "無法連到 Netflix 控制頁面，請稍後再試。",
    "netflix_controller_unavailable": "無法載入 Netflix 遙控控制，請稍後再試。",
    "netflix_target_unsupported": "Netflix 目前畫面不是可控制的主要頁面。",
    "netflix_focus_unavailable": "找不到可操作的 Netflix 項目，請稍後再試。",
    "netflix_input_unavailable": "找不到可輸入的 Netflix 欄位，請先選取輸入欄。",
    "netflix_video_unavailable": "目前沒有可播放或暫停的 Netflix 影片。",
}

class NetflixAction(StrEnum):
    FOCUS_PRIMARY = "FOCUS_PRIMARY"
    FOCUS_EDITABLE = "FOCUS_EDITABLE"
    FOCUS_NEXT = "FOCUS_NEXT"
    NAV_UP = "NAV_UP"
    NAV_DOWN = "NAV_DOWN"
    NAV_LEFT = "NAV_LEFT"
    NAV_RIGHT = "NAV_RIGHT"
    OK = "OK"
    BACK = "BACK"
    PLAY_PAUSE = "PLAY_PAUSE"

FocusFingerprint = dict[str, str | int]

def _is_netflix_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "netflix.com" or host.endswith(".netflix.com")

def select_netflix_target(pages: list[dict[str, Any]]) -> str:
    netflix = [page for page in pages if _is_netflix_host(str(page.get("url", "")))]
    if any(page.get("type") != "page" or page.get("openerId") for page in netflix):
        raise CommandExecutionError("netflix_target_unsupported", ERROR_MESSAGES["netflix_target_unsupported"])
    top = [page for page in netflix if page.get("webSocketDebuggerUrl")]
    if len(top) > 1:
        raise CommandExecutionError("netflix_target_unsupported", ERROR_MESSAGES["netflix_target_unsupported"])
    if not top:
        raise CommandExecutionError("netflix_page_unavailable", ERROR_MESSAGES["netflix_page_unavailable"])
    return str(top[0]["webSocketDebuggerUrl"])
```

- [ ] **Step 4: 實作每指令短連線、版本確認、一次重試與文字保密**

```python
class NetflixPageController:
    def __init__(self, timeout: float = 8.0, runtime_path: Path | None = None) -> None:
        self._timeout = timeout
        self._runtime_source = (runtime_path or Path(__file__).with_name("netflix_control.js")).read_text(encoding="utf-8")
        self._focus: FocusFingerprint | None = None
        self._command_id = 0

    async def execute(self, port: int, action: NetflixAction) -> None:
        async def operation(socket: Any) -> None:
            self._accept_runtime_result(await self._run_runtime(socket, action))
        await self._run_transaction(port, operation)

    async def type_text(self, port: int, text: str) -> None:
        async def operation(socket: Any) -> None:
            self._accept_runtime_result(await self._run_runtime(socket, NetflixAction.FOCUS_EDITABLE))
            await self._call(socket, "Input.insertText", {"text": text})
        await self._run_transaction(port, operation)
```

固定行為：

1. 每個 attempt 都重新 `_list_pages(port)`、`select_netflix_target()`、`async with websockets.connect(...)`；成功或失敗都離開 context。
2. `_run_transaction()` 最多兩個 attempts；HTTP／socket／CDP／版本注入暫時錯誤可重試，target／DOM 固定錯誤直接傳出。
3. `_run_runtime()` 先讀固定 version expression；不等於 `"1"` 才 evaluate 本地 source，並再次確認 version。
4. action expression 只序列化 `NetflixAction.value` 與七欄白名單 `_focus`；不得接受手機 expression、selector 或 URL。
5. `_accept_runtime_result()` 只接受 `ERROR_MESSAGES` 中的 code；focus 字串每欄最多 256 字，拒絕 `value` 與額外欄位。
6. `text` 只放在 `Input.insertText` params；不得進 logger、exception、state、ack 或 runtime result。

- [ ] **Step 5: 執行 controller tests**

Run（repo root）：`.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_netflix_page.py`

Expected: PASS；每個成功 public call 一條短 socket，暫時失敗最多兩條，確定性錯誤只有一次 attempt。

- [ ] **Step 6: Commit**

```bash
git add backend/app/applications/netflix_page.py backend/tests/test_netflix_page.py
git commit -m "feat: add Netflix page controller"
```

---

### Task 3: Manager, Ports, CommandBus, PWA, and Expo Clean Cutover

**Files:**
- Modify: `backend/app/applications/manager.py`
- Modify: `backend/app/config.py`
- Delete: `backend/app/applications/chrome_page.py`
- Delete: `backend/tests/test_chrome_page.py`
- Modify: `backend/tests/test_applications.py`
- Modify: `backend/tests/test_command_bus.py`
- Modify: `backend/tests/test_config.py`
- Modify: `backend/tests/test_protocol_security.py`
- Modify: `frontend/src/remote/RemotePage.test.tsx`
- Modify: `frontend/src/api/controllerSocket.test.ts`
- Modify: `mobile/src/screens/RemoteScreen.test.tsx`
- Modify: `mobile/src/api/controllerSocket.test.ts`
- Verify unchanged: `backend/app/commands/ports.py`、`backend/app/commands/bus.py`、三份 protocol type 檔。

**Interfaces:**
- Consumes: Task 2 `NetflixPageController.execute(port: int, action: NetflixAction)` 與 `type_text(port: int, text: str)`。
- Consumes unchanged: `ApplicationPort.forward_command(Command)`、`ApplicationPort.type_text(str)`。
- Produces: `ApplicationManager(..., netflix_page: NetflixPageController | None = None, netflix_debug_port: int | None = None)`；移除 `page_input` 與 `_page_input`。
- Produces: `NETFLIX_ACTIONS: dict[Command, NetflixAction]`，包含 NAV 四向、OK、BACK、PLAY_PAUSE、TAB→FOCUS_NEXT。
- Produces unchanged: version `1`、現有 command 字串、`TextInputMessage`、ack 與 `HOME → return_home()`。

- [ ] **Step 1: 先寫 manager／config／bus failing tests**

在 `test_applications.py` 以此 fake 取代 `FakePageInput`：

```python
@dataclass
class FakeNetflixPageController:
    actions: list[tuple[int, NetflixAction]] = field(default_factory=list)
    typed: list[tuple[int, str]] = field(default_factory=list)
    failure: CommandExecutionError | None = None

    async def execute(self, port: int, action: NetflixAction) -> None:
        if self.failure is not None:
            raise self.failure
        self.actions.append((port, action))

    async def type_text(self, port: int, text: str) -> None:
        if self.failure is not None:
            raise self.failure
        self.typed.append((port, text))
```

加入 tests：

- `test_netflix_page_commands_use_controller_without_windows_input`
- `test_netflix_controller_failure_never_falls_back_to_windows_input`
- `test_browser_back_still_uses_alt_left_path`
- `test_netflix_text_uses_controller_and_is_not_logged`
- `test_home_keeps_existing_netflix_window_ownership_behavior`
- `test_netflix_launch_uses_profile_fullscreen_loopback_cdp_and_no_adblock`
- `test_netflix_initial_focus_failure_rolls_back_only_the_owned_window`
- `test_netflix_commands_and_text_use_only_application_port`
- `test_netflix_error_becomes_failed_ack_without_state_change`

`test_config.py` 加入 HTTPS Netflix host tests；`test_protocol_security.py` 鎖定 256 字、257 字拒絕、extra `javascript`／`selector`／`url`／`raw_key` 欄位拒絕。

- [ ] **Step 2: 加入 PWA／Expo 既有協定回歸**

PWA tests 觸發四方向、OK、BACK、PLAY_PAUSE 與 256 字文字，assert exact command；ControllerSocket assert wire 只有 version 1 `command` 與 `text_input`。Expo `RemoteScreen.test.tsx` 透過 `Dpad`、`MediaControls`、`TextInputModal` props 驗證相同行為與失敗 ack；native socket test 使用：

```ts
const commandAck = socket.sendCommand('PLAY_PAUSE')
const textAck = socket.sendTextInput('x'.repeat(256))
const messages = ws.sent.map((raw) => JSON.parse(raw)).filter((message) => message.type !== 'authenticate')
expect(messages.map(({ type }) => type)).toEqual(['command', 'text_input'])
expect(messages[0]).toMatchObject({ version: 1, command: 'PLAY_PAUSE' })
expect(messages[1]).toMatchObject({ version: 1, text: 'x'.repeat(256) })
sendAck(ws, messages[0].request_id)
sendAck(ws, messages[1].request_id)
await expect(commandAck).resolves.toMatchObject({ success: true })
await expect(textAck).resolves.toMatchObject({ success: true })
```

- [ ] **Step 3: 執行 RED gate**

Run（repo root）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_applications.py backend\tests\test_command_bus.py backend\tests\test_config.py backend\tests\test_protocol_security.py
Push-Location frontend; npm test -- src/remote/RemotePage.test.tsx src/api/controllerSocket.test.ts; Pop-Location
Push-Location mobile; npm test -- --runInBand src/screens/RemoteScreen.test.tsx src/api/controllerSocket.test.ts; Pop-Location
```

Expected: backend FAIL，因 manager 尚無 `netflix_page` 且 BACK 仍走 Windows；PWA／Expo 可先 PASS，因 UI／wire 本來就不需修改。整體 RED gate 由 backend 可觀察 clean-cutover 契約提供。

- [ ] **Step 4: 實作 config 與 manager 單一路徑**

`urls.netflix` 固定要求 scheme `https`，hostname 為 `netflix.com` 或以 `.netflix.com` 結尾。Manager 使用唯一 mapping：

```python
NETFLIX_ACTIONS: dict[Command, NetflixAction] = {
    Command.NAV_UP: NetflixAction.NAV_UP,
    Command.NAV_DOWN: NetflixAction.NAV_DOWN,
    Command.NAV_LEFT: NetflixAction.NAV_LEFT,
    Command.NAV_RIGHT: NetflixAction.NAV_RIGHT,
    Command.OK: NetflixAction.OK,
    Command.BACK: NetflixAction.BACK,
    Command.PLAY_PAUSE: NetflixAction.PLAY_PAUSE,
    Command.TAB: NetflixAction.FOCUS_NEXT,
}

async def forward_command(self, command: Command) -> None:
    self.require_input_target(self._active_app)
    if self._active_app is ActiveApp.NETFLIX:
        action = NETFLIX_ACTIONS.get(command)
        if action is None:
            raise CommandExecutionError("command_not_supported", "Netflix 不支援這個遙控指令。")
        await self._netflix_page.execute(self._netflix_debug_port, action)
        return
    if command is Command.BACK and self._active_app is ActiveApp.BROWSER:
        self._input.send_browser_back()
        return
    self._input.send_command(command)
```

Netflix `type_text()` 只呼叫 controller。移除 `_anchor_netflix_login()`、`ready()`、`focus_login_field()`、`focus_next_field()` 與所有 `_page_input`。新開／重用 Netflix 後呼叫 `FOCUS_PRIMARY`；初始化失敗時，新行程只關閉該 tracked Netflix，重用視窗只重新最小化並回 launcher，再傳出固定錯誤，不送 Windows input。完成遷移後刪除舊 module 與 test。

- [ ] **Step 5: 確認 ports／bus／protocol 無介面擴張**

Run（repo root）：

```powershell
git diff --exit-code -- backend/app/commands/ports.py backend/app/commands/bus.py backend/app/protocol.py frontend/src/types/protocol.ts mobile/src/types/protocol.ts
```

Expected: PASS 且無輸出。`ApplicationPort.forward_command/type_text` 與既有 bus 已足夠；任何差異都移除後重跑。

- [ ] **Step 6: 執行 targeted tests**

Run（repo root）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests\test_netflix_page.py backend\tests\test_applications.py backend\tests\test_command_bus.py backend\tests\test_config.py backend\tests\test_protocol_security.py
Push-Location frontend; npm test -- src/netflix/netflixControl.test.ts src/remote/RemotePage.test.tsx src/api/controllerSocket.test.ts; Pop-Location
Push-Location mobile; npm test -- --runInBand src/screens/RemoteScreen.test.tsx src/api/controllerSocket.test.ts; npm run typecheck; Pop-Location
```

Expected: PASS；backend 不再引用 `chrome_page`，兩種手機只發 version 1 `command`／`text_input`。

- [ ] **Step 7: Commit**

```bash
git add backend/app/applications/manager.py backend/app/config.py backend/app/applications/chrome_page.py backend/tests/test_chrome_page.py backend/tests/test_applications.py backend/tests/test_command_bus.py backend/tests/test_config.py backend/tests/test_protocol_security.py frontend/src/remote/RemotePage.test.tsx frontend/src/api/controllerSocket.test.ts mobile/src/screens/RemoteScreen.test.tsx mobile/src/api/controllerSocket.test.ts
git commit -m "feat: route Netflix controls through page adapter"
```

---

### Task 4: User and Architecture Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Consumes: Task 3 launch flags、`NetflixPageController`、短 CDP transaction、PWA／Expo 共用 protocol、HOME ownership。
- Produces: 不再聲稱 Netflix 使用 Edge；文件一致說明專用 Chrome profile、Widevine、localhost CDP、安全邊界與手機免滑鼠流程。

- [ ] **Step 1: 建立文件 RED gate**

Run（repo root）：`Select-String -Path README.md,docs/ARCHITECTURE.md -Pattern 'Netflix.*Edge|Edge.*Netflix'`

Expected: 輸出 README 現有 `Microsoft Edge for Netflix` 與 `Netflix opens Edge`，證明文件契約過時。

- [ ] **Step 2: 更新 README**

精確寫明 Netflix 使用 Chrome、`config/chrome-netflix-profile`、`--start-fullscreen`、localhost CDP；登入／Widevine 仍由 Chrome／Netflix 處理；PWA 與 Expo 可用方向、OK、BACK、PLAY_PAUSE、文字完成免滑鼠流程；HOME 只最小化 tracked Netflix。Generic Browser 與 TV launcher 可繼續提及 Edge。

- [ ] **Step 3: 更新 ARCHITECTURE**

Mermaid 加入 `Apps --> NetflixPage[NetflixPageController] -->|short CDP 127.0.0.1| NetflixDOM[Netflix DOM]`。Backend modules 表加入 `netflix_page.py` 與 `netflix_control.js`；Command flow 寫明每指令短連線、唯一 top-level target、版本確認、動作後關閉；Ownership 使用實際 `ApplicationManager.return_home()`，說明 Netflix 不經 Windows input 而 HOME 不進 DOM。

- [ ] **Step 4: 執行文件一致性檢查**

Run（repo root）：

```powershell
if (Select-String -Path README.md,docs/ARCHITECTURE.md -Pattern 'Netflix.*Edge|Edge.*Netflix') { exit 1 }
Select-String -Path README.md,docs/ARCHITECTURE.md -Pattern 'chrome-netflix-profile|NetflixPageController|127\.0\.0\.1|/remote|mobile/'
```

Expected: 第一個命令 exit `0` 且無輸出；第二個命令在兩份文件找到新架構關鍵字。

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: document Netflix TV navigation"
```

---

## Final Automated Verification Gate

- [ ] Backend full suite：repo root 執行 `.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests`；Expected: PASS。
- [ ] Frontend full gate：`frontend/` 執行 `npm run lint && npm run build && npm test`；Expected: PASS，且 package／lockfile 無變更。
- [ ] Expo full gate：`mobile/` 執行 `npm run typecheck && npm test -- --runInBand`；Expected: PASS。
- [ ] Protocol gate：`git diff HEAD~4 -- backend/app/protocol.py frontend/src/types/protocol.ts mobile/src/types/protocol.ts`；Expected: 無輸出。
- [ ] Clean-cutover gate：確認 `manager.py` 無 `ChromePageInput`、`_page_input`、`focus_login_field`、`focus_next_field`，且 `chrome_page.py` 不存在。
- [ ] 安全 gate：確認 controller/runtime 無 `Network.*`、`Storage.*`、Cookie、MediaKey、input `.value`、記錄文字的 logger call。

## Windows 11 Real Netflix Phone-Only Smoke Gate

- [ ] 分別配對 `/remote` PWA 與 `mobile/` Expo，確認兩者不需 protocol 升級。
- [ ] 由 PWA 開 Netflix，確認專用 profile、真正全螢幕、CDP 只監聽 `127.0.0.1`。
- [ ] 登出狀態只用 PWA 完成帳號、下一步、密碼、驗證碼；刻意輸入錯誤，確認焦點回欄位，log／ack／state 無輸入內容。
- [ ] 只用 PWA 完成選人、首頁列／片卡、搜尋、詳情、播放、PLAY_PAUSE、BACK；確認白框、紅光暈、自動置中與方向邊界。
- [ ] 播放 Widevine 內容並另開其他 Chrome video；Netflix PLAY_PAUSE 不影響其他 video。
- [ ] 詳情按 BACK 先關 overlay；無 overlay 才 history。HOME 只最小化 tracked Netflix 並回 launcher。
- [ ] 重開 Netflix 確認登入保留；換頁、返回、重新整理、DOM 重建後，下一指令重注入並語意恢復。
- [ ] 用 Expo 重做選人、導航、搜尋文字、詳情、播放、PLAY_PAUSE、BACK、HOME；結果與 PWA 相同。
- [ ] 製造 CDP 中斷或 runtime version 不符；只重試一次、只一個 DOM 動作、無 SendInput／Alt+Left 第二次觸發，失敗顯示固定中文錯誤。
- [ ] 開額外 Netflix popup／第二個 top-level target；回 `Netflix 目前畫面不是可控制的主要頁面。`，不控制其他 target。
- [ ] LAN 另一裝置無法連 CDP；Remote WS 的 JS、selector、URL、raw key、CDP method、257 字文字均被拒絕。
- [ ] 每個頁面指令後 CDP websocket 關閉，沒有常駐 listener；document/context 失效只在下一指令重注入。

## Plan Self-Review Checklist

- [ ] Spec coverage：Task 1 覆蓋 DOM／焦點／動作；Task 2 覆蓋 CDP／target／版本／重試／錯誤／保密；Task 3 覆蓋 clean cutover、HOME、PWA＋Expo 與 protocol 不變；Task 4 覆蓋 README／ARCHITECTURE；final gates 覆蓋三套驗證與 Windows 11 實機。
- [ ] 禁用詞掃描：全文不含暫定標記、延後實作語句、模糊轉述或未具名測試要求。
- [ ] Type consistency：`NetflixAction`、`FocusFingerprint`、`NetflixPageController.execute/type_text`、`NETFLIX_ACTIONS`、`__freeTvNetflixControl.version/run` 在後續 task 使用完全相同拼字、參數與回傳型別。
- [ ] Scope：沒有新 wire message、依賴、通用 browser automation、Windows fallback、DRM／Cookie／request 修改或 PWA／Expo UI redesign。
- [ ] Commit boundary：四個 task 各自一個 Conventional Commit；final verification 與 smoke 不產生空 commit。
