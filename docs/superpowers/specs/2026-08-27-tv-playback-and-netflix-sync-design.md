# TV 播放與 Netflix 狀態同步設計規格 (TV Playback and Netflix Sync Design Specification)

## 1. 目標 (Objective)

本規格定義 FreeTV 系統在 Windows 11 PC TV Box 環境下，針對客廳大螢幕播放體驗之串流通知阻擋、YouTube 自動全螢幕、以及 Netflix 獨立應用面板（Standalone App Window）與狀態廣播同步（NetflixContext）與行動端情境卡片（Context Card）設計。

核心目標包含：

1. **Netflix 獨立面板化 (`Chrome --app=<url>`)**：在 Windows 平台無官方認證 Android TV 原生 App（硬體 Widevine ESN）之前提下，採用 `Chrome --app=<Netflix URL>` 獨立應用程式視窗（Standalone App Window）作為 Windows 端最接近電視 App 的獨立面板。徹底移除分頁列（Tab Bar）、網址列（Omnibox）與瀏覽器外框（Browser Chrome），保留標準 Google Chrome Widevine L3 DRM 播放能力、專用 `config/chrome-netflix-profile`、`--start-fullscreen`、`127.0.0.1` CDP 控制、`--disable-extensions` 與通知阻擋旗標。明確界定其底層仍為 Netflix 官方網頁，不宣稱 Android TV Native UI，但透過片卡 D-Pad 幾何導航與 OK 直接播放組合動作營造電視 App 的純粹觀影體驗。
2. **消除網頁通知與權限干擾**：在 TV 專用 Chrome 實例中嚴格套用 `--disable-notifications` 與 `--deny-permission-prompts`，徹底阻絕推播彈窗與權限請求；沿用專案現有之 `config/chrome-netflix-profile` 與 `config/chrome-tv-profile` 專用設定檔，絕不修改使用者個人電腦的日常 Chrome 瀏覽器。
3. **YouTube 窄責任自動全螢幕 (`YoutubeFullscreenController`)**：於獨立新檔 `backend/app/applications/youtube_fullscreen.py` 實作窄責任控制器。僅在 YouTube / News 為活動應用程式時，由管理員啟動 bounded 1 秒週期的短 CDP 探測；於偵測到 watch / live 路由（包含 `#/watch?v=`、`/watch?v=`、`/shorts/`、`/live/`）且視訊元素就緒時，執行單次 `Runtime.evaluate(userGesture=true)` 全螢幕指令。同影片識別碼（Video Identity）僅觸發一次，無 fallback，發送後若結果未知絕不重試，使用者手動退出全螢幕亦不強制拉回。
4. **Netflix 短連線安全狀態廣播 (`NetflixContext`)**：延續 2026-08-25 規格之短 CDP 連線架構，**嚴禁常駐 CDP 連線與背景長輪詢**。TV 端至手機端為純粹之安全狀態廣播（Safe State Broadcast），手機端至 TV 端為既有 typed command 與 text_input（嚴禁回讀輸入欄位）。每次 Netflix 指令、文字輸入或複合動作完成後，由 runtime 回傳安全情境；非同步換頁與直接播放在同一短 transaction 內完成 bounded settle，由 `CommandBus` 唯一更新 `StateStore` 並廣播至 `/remote` PWA 與 `mobile/` Expo。離開 Netflix 時立即將 context 清空為 `None`。
5. **型別化情境卡片 (Inline Context Card) 與相容提交 (`submit: bool = False`)**：為既有 `TextInputMessage` 增加 optional `submit: bool = False`（維持 Protocol v1 相容，不新增 wire message type）。Context Card 依據型別化 context 渲染非侵入式 inline 情境卡片，自動適配 email、password（安全遮蔽）、code 輸入模式，送出時帶 `submit=true` 觸發一次性 type+submit 複合動作；送出即清空本地暫存；片單瀏覽時顯示當前片名（`focused_title` 僅限 `stage=browse`），Expo 端補齊 TAB 鍵控制，全程落實零機密外洩（Zero-Leakage）。

---

## 2. 問題根因與客廳平台限制分析 (Root Causes & Platform Constraints)

1. **Windows 端 Netflix TV 原生生態缺位 (Lack of Certified Android TV App on Windows)**：
   - 智慧電視盒與投影機通常運行官方認證之 Android TV Native App，內建硬體級 Widevine L1 與 ESN（Electronic Serial Number）認證，提供原生遙控器焦點模型。
   - Windows 平台無法合法且可靠地複製或直跑該認證 App；而客廳 TV Box 使用標準瀏覽器全螢幕時，仍易因意外滑鼠點擊或系統熱鍵露出分頁標籤、網址列與右鍵選單，破壞電視沉浸感。
2. **Windows 容器與殼層替代方案限制 (Windows Wrapper Constraints)**：
   - **Microsoft Store Netflix App**：現已改版為 PWA 包裝，且無法由外部進程指定 CDP remote debugging 埠號進行精確遙控。
   - **WebView2 / Electron / Tauri 自製 Shell**：缺乏 Google 商業授權之 Widevine CDM 與 Verified Media Path (VMP) 數位簽章，極易導致 1080p/4K 播放失敗或黑畫面，且客製視窗管理增加維護負擔。
   - **Android 模擬器 (Emulator / Sideloaded APK)**：缺乏官方 ESN 認證會被 Netflix 伺服器降級至 480p 或直接拒絕登入，且模擬器資源開銷過大、啟動緩慢。
3. **串流網頁權限彈窗污染 (Notification & Permission Prompts)**：
   - 網頁版 YouTube、新聞直播及串流服務在啟動時常跳出「允許通知」、「存取位置」等彈窗，遮蔽視訊焦點且無法透過方向鍵直接關閉。
4. **全螢幕手勢安全性要求 (Fullscreen User Gesture Constraint)**：
   - 現代瀏覽器嚴格限制 `requestFullscreen()` 必須帶有實體使用者手勢（User Gesture）。一般後端腳本若無 CDP `userGesture=true` 旗標將被瀏覽器阻擋。
5. **Netflix 網頁版非同步轉場與非電視 UX (Asynchronous State & Web UX)**：
   - Netflix 官方網頁版係為滑鼠設計，且轉場（如登入驗證、密碼錯誤、片單載入）均為非同步 DOM 變更。若無狀態廣播，手機遙控端無法得知電視當前是需要輸入 Email、密碼、OTP，還是已進入片單。
6. **憑證與機密洩漏風險 (Sensitive Credential Leakage)**：
   - 若同步機制讀回輸入框值、長度或 Session 密鑰並廣播至 WebSocket，將造成嚴重的安全漏洞。必須在協定與架構層面確保機密零讀回。

---

## 3. 評估方案比較 (Evaluated Approaches)

### 3.1 視窗容器與運行模式選型比較

```
+---------------------------------------------------------------------------------------------------------------+
|                                    Windows 視窗容器與運行模式評估                                               |
+------------------------------------+--------------------------+-----------------------+-----------------------+
| 評估維度                           | 方案 1: Chrome --app 模式 | 方案 2: Store PWA /   | 方案 3: Android 模擬器|
|                                    | (選定方案)                | WebView2 / Electron   | / Sideloaded APK      |
+------------------------------------+--------------------------+-----------------------+-----------------------+
| 視窗純淨度 (無 Tab/Omnibox)        | 完全純淨 (獨立面板視窗)   | 完全純淨              | 視模擬器視窗而定      |
| Widevine L3 / DRM 播放可靠度       | 原生 Chrome 支持 (極高)  | 不可靠 (缺乏 VMP 簽章)| 失敗/降級 (無 ESN 認證|
| 127.0.0.1 CDP 遙控與注入支援       | 完整支援 (指定隨機埠)    | 無法指定或不完整      | 需依賴 ADB，脆弱延遲  |
| 系統資源佔用與啟動速度             | 低/極快 (沿用 Chrome)    | 中等                  | 極高/極慢 (VM 虛擬化) |
| 設定檔隔離與登入保留               | 專用 profile 完全支援    | 設定檔受限            | 虛擬磁碟映像檔        |
| 結論                               | 【採納】                 | 【未採用】            | 【未採用】            |
+------------------------------------+--------------------------+-----------------------+-----------------------+
```

### 3.2 狀態同步與遙控互動方案比較

```
+-----------------------------------------------------------------------------------------------+
|                                  狀態同步與互動架構評估                                         |
+------------------------------------+--------------------------+-------------------------------+
| 特性 / 維度                         | 方案 A: Typed Context    | 方案 B: status_message 字串   | 方案 C: Full-page Wizard     |
|                                    | Card (選定方案)           | 解析/擴充 (未採用)             | 流程 (未採用)                 |
+------------------------------------+--------------------------+-------------------------------+
| 狀態定義與合約                      | 強型別列舉與安全結構體   | 弱型別單一字串訊息             | 獨立全螢幕表單精靈頁面       |
| CDP 連線生命週期                    | 指令級短連線 (無常駐)    | 指令級短連線                   | 常駐連線/長輪詢               |
| 雙端一致性 (Backend/PWA/Expo)       | 高 (編譯期/型別檢查保證) | 低 (脆弱的正則/文字比對)       | 中 (需多端維護獨立流程)       |
| 隱私與安全性 (Zero-Leakage)         | 極高 (零值回讀/立即清空) | 中 (容易在字串中混入敏感資訊) | 低 (在行動端暫存完整憑證)     |
| 遙控器 UI 體驗                      | Inline 情境卡 (非侵入)   | 僅狀態文字                     | 強制全頁彈窗 (阻斷操作)       |
| 瀏覽與導航感知                      | 支援 (片名感知與直播)    | 不支援                        | 不支援 (僅限登入)             |
| 異步換頁穩定度                      | Bounded Settle 同步更新  | 無 Settle 保證                 | 易受網路延遲中斷             |
+------------------------------------+--------------------------+-------------------------------+
```

- **方案 1 + 方案 A（選定）**：
  - 以 `Chrome --app=<url>` 提供乾淨無外框之電視獨立視窗。
  - 後端維持每指令短 CDP 連線，動作完成後在同一次 transaction 內完成 bounded settle 並回傳強型別 `NetflixContext`。
  - `CommandBus` 唯一更新狀態並廣播 `StateMessage`，PWA/Expo 呈現非侵入式 inline 情境卡片。
- **未採用方案**：
  - Store PWA / 自製 WebView2 Shell：DRM 與 CDP 支援不足。
  - Android 模擬器：無 ESN 認證且系統負擔過重。
  - 字串正則解析 (方案 B) 與全頁登入精靈 (方案 C)：維護成本高、體驗中斷、安全風險高。

---

## 4. 系統架構、啟動參數與 State Ownership

### 4.1 TV 專用 Netflix Standalone App 啟動參數

Netflix 視窗由 `ApplicationManager._chrome_desktop_args` 產生啟動指令，明確採用單一 `--app=<url>` 參數，**嚴禁重複夾帶 positional URL**：

```python
# backend/app/applications/manager.py

def _chrome_desktop_args(self, url: str, profile_dir: Path) -> list[str]:
    chrome = self._executables.get("chrome")
    if chrome is None:
        raise CommandExecutionError("chrome_not_found", "未安裝或尚未設定 Chrome。")
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
        *TV_CHROME_NOTIFICATION_FLAGS,  # --disable-notifications, --deny-permission-prompts
        f"--app={url}",                 # 單一 Standalone App 參數，無額外 positional URL
    ]
```

- **視窗與進程持有 (Ownership & Tracking)**：沿用既有 PID、HWND 視窗句柄追蹤機制；`HOME` 命令僅最小化 Netflix 視窗，再次開啟時透過 `_focus_existing` 立即喚醒，保留登入會話與播放記憶。

### 4.2 端到端資料流與 Ownership 定義

```
+--------------------------------------------------------------------------------------------------+
|                                    TV Playback & Sync Data Flow                                  |
+--------------------------------------------------------------------------------------------------+

  [ /remote PWA 或 mobile/ Expo 遙控器 ]
        |
        | 1. 發送既有 typed command (NAV_*, OK, BACK, TAB) 或 text_input (可選 submit: bool)
        v
  [ Remote WebSocket (ws:// or wss://) ]
        |
        | 2. 序列化、驗證與限流
        v
  [ backend: CommandBus ] <=============================================+
        |                                                               |
        | 3. 分派至 ApplicationPort (ApplicationManager)                |
        v                                                               |
  [ backend: ApplicationManager ]                                       |
        |                                                               |
        | 4. 轉交至 NetflixPageController                               |
        v                                                               |
  [ backend: NetflixPageController ]                                    |
        |                                                               |
        | 5. 建立 Short CDP Connection (只連 127.0.0.1 專用 port)       |
        |    - 注入/確認固定控制程式                                     |
        |    - 執行目標動作 (DOM click / key / insertText / composite)  |
        |    - 遇換頁操作時在同一 transaction 內進行 Bounded Settle     |
        |    - 提取安全 NetflixContext (零機密回讀)                     |
        |    - 立即關閉 CDP 連線 (嚴禁常駐 socket)                     |
        v                                                               |
  [ Netflix Runtime Result: Safe NetflixContext ]                       |
        |                                                               |
        | 6. 回傳至 NetflixPageController.execute/type_text -> NetflixContext
        v                                                               |
  [ ApplicationManager.forward_command/type_text -> NetflixContext | None ]
        |                                                               |
        | 7. 回傳最新 context 至 CommandBus ----------------------------+
        v
  [ backend: CommandBus (唯一 State Ownership) ]
        |
        | 8. 呼叫 StateStore.update(netflix_context=...) 更新全域狀態
        |    - 嚴禁 ApplicationManager 直接向客戶端廣播
        v
  [ backend: WebSocket Registry ]
        |
        | 9. 廣播 StateMessage (新增 optional netflix_context)
        +-----------------------------------+
        |                                   |
        v                                   v
  [ frontend: PWA RemotePage ]        [ mobile: Expo RemoteScreen ]
        |                                   |
        | 10. 渲染 Inline Context Card      | 10. 渲染 Inline Context Card
        |     - 自動切換輸入模式與安全遮蔽   |     - 自動切換輸入模式與安全遮蔽
        |     - 顯示片名與直播輔助           |     - 顯示片名與直播輔助，提供 TAB 鍵
        |     - 使用者輸入送出即清空本地暫存 |     - 使用者輸入送出即清空本地暫存
```

### 4.3 介面簽章與 State Ownership 規範

1. **元件介面簽章 (`backend/app/commands/ports.py`)**：
   - `NetflixPageController.execute(command: Command) -> NetflixContext`
   - `NetflixPageController.type_text(text: str, submit: bool = False) -> NetflixContext`
   - `ApplicationPort.open(app: ActiveApp) -> NetflixContext | None`
   - `ApplicationPort.forward_command(command: Command) -> NetflixContext | None`
   - `ApplicationPort.type_text(text: str, submit: bool = False) -> NetflixContext | None`
2. **State Ownership 與廣播權限**：
   - **`CommandBus` 是唯一的狀態更新與廣播擁有者**。`ApplicationManager` 僅作為應用程式生命週期管理與命令轉交者，**嚴禁直接呼叫廣播介面**。
   - 所有測試 Fake（如 `FakeApplications`）同步實作上述回傳型別。
3. **生命週期與狀態清空 (Lifecycle & Invalidation)**：
   - **進入 Netflix / 執行指令**：`CommandBus` 依據 `ApplicationPort` 回傳之 `NetflixContext` 更新 `StateStore` 並觸發廣播。
   - **離開 Netflix**：當開啟非 Netflix 應用程式（YouTube、News、Live TV、Browser）、按下 `HOME` 返回桌面、或應用程式關閉/崩潰時，`CommandBus` 立即將 `state.netflix_context` 更新為 `None` 並廣播清空。
   - **PWA / Expo 端清空**：客戶端收到 `netflix_context: null` 時，立即卸載 Context Card 並重設輸入緩衝區。

---

## 5. 瀏覽器通知與權限提示阻擋 (Notification & Permission Suppression)

### 5.1 TV 專用 Chrome 啟動參數

針對 TV 專用串流實例，啟動參數固定僅新增以下兩項標準 Chromium 旗標：

```python
# backend/app/applications/chrome_policy.py

TV_CHROME_NOTIFICATION_FLAGS = [
    "--disable-notifications",    # 停用 Web Notifications 系統
    "--deny-permission-prompts",  # 自動拒絕所有權限請求彈窗 (Geolocation, Push, Notification 等)
]
```

### 5.2 專用 Profile 與日常 Chrome 零干擾

- **設定檔隔離**：完全沿用專案現有之專用設定檔目錄：
  - Netflix 專用：`config/chrome-netflix-profile`
  - YouTube / News 專用：`config/chrome-tv-profile`
- **零干擾保證**：絕不修改或干擾使用者日常 Chrome 之 `%LOCALAPPDATA%\Google\Chrome\User Data` 設定檔，亦不修改 Windows 全域登錄檔。

---

## 6. YouTube 窄責任自動全螢幕 (`backend/app/applications/youtube_fullscreen.py`)

### 6.1 窄責任控制器 (`YoutubeFullscreenController`)

為達成職責單一與資源節約，於獨立新檔 `backend/app/applications/youtube_fullscreen.py` 實作：

1. **生命週期管理**：
   - 僅在 YouTube 或 News 處於活動狀態（`active_app in [ActiveApp.YOUTUBE, ActiveApp.NEWS]`）時，由 `ApplicationManager` 啟動 bounded 1 秒週期的短 CDP 探測任務。
   - 當切換至 `HOME`、切換其他應用程式或系統關閉時，立即停止該探測任務。
2. **無常駐 Socket**：每次 1 秒探測均建立短 CDP 連線，讀取狀態後立即關閉，嚴禁常駐 WebSocket 連線。

### 6.2 路由匹配與 Video Ready 判定

探測流程包含以下條件檢驗：

1. **路由判斷 (Route Pattern)**：
   - 標準網址：包含 `/watch?v=`、`/shorts/`、`/live/`。
   - TV Hash 網址：包含 `#/watch?v=`。
2. **視訊就緒 (Video Ready)**：
   - 頁面中的 `<video>` 元素存在且 `readyState >= 2`（`HAVE_CURRENT_DATA`）。
   - 頁面當前未處於全螢幕狀態（`document.fullscreenElement === null`）。
3. **Video Identity 與單次觸發**：
   - 從 URL 提取唯一的影片識別碼（Video Identity，例如 `v` 參數值或 shorts ID）。
   - 若 `current_video_id === last_fullscreen_video_id`，則直接略過。

### 6.3 單次手勢執行與無重試策略 (Single User Gesture Action, No Retry)

```python
# backend/app/applications/youtube_fullscreen.py

async def try_trigger_fullscreen(cdp_session, video_id: str) -> bool:
    # 標記已處理 (在發送動作前立即記錄，確保每 video identity 僅執行一次)
    cdp_session.last_fullscreen_video_id = video_id

    # 透過 CDP Runtime.evaluate 帶入 userGesture=True 呼叫原生全螢幕
    await cdp_session.evaluate_with_user_gesture("""
        (() => {
            const player = document.querySelector('#movie_player') || document.querySelector('video');
            if (player && player.requestFullscreen && !document.fullscreenElement) {
                player.requestFullscreen().catch(() => {});
            }
        })()
    """)
    return True
```

- **無第二種 Fallback**：不執行鍵盤模擬或其他備用 DOM 點擊，保持行為確定。
- **發送後結果未知不重試 (No Retry on Unknown Outcome)**：全螢幕動作發送後若結果未知或未成功，絕不重複重試。
- **手動退出不拉回**：若使用者主動按 `Esc` 退出全螢幕以查看留言或推薦，由於 `last_fullscreen_video_id` 已被記錄，系統在同一影片內絕不再次強制拉回全螢幕；唯有切換至下一支影片產生新 video identity 時方可再次觸發。

---

## 7. 協定定義與 NetflixContext 精確列舉 (Protocol Specification)

### 7.1 Python 協定定義 (`backend/app/protocol.py`)

採用現有 `StrEnum` 與 `ConfigDict(frozen=True)` / `ConfigDict(extra="forbid")` 風格，並為 `TextInputMessage` 新增 backward-compatible 之 `submit: bool = False`：

```python
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

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

    stage: NetflixStage = Field(..., description="當前 Netflix 頁面階段")
    input_kind: NetflixInputKind = Field(..., description="當前聚焦或活動輸入框類型")
    has_error: bool = Field(default=False, description="頁面是否出現錯誤警示")
    can_submit: bool = Field(default=False, description="當前階段是否具備可點選的提交按鈕")
    focused_title: str | None = Field(
        default=None,
        max_length=120,
        description="當前聚焦片名 (僅允許在 stage=browse 時設定，其餘 stage 必須為 None)",
    )

class TextInputMessage(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["text_input"]
    request_id: str = Field(min_length=1, max_length=64, pattern=REQUEST_ID_PATTERN)
    text: str = Field(min_length=1, max_length=256)
    submit: bool = Field(default=False, description="是否在輸入完成後自動點選主要送出/繼續按鈕")

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

### 7.2 TypeScript 協定定義 (`frontend/src/types/protocol.ts`, `mobile/src/types/protocol.ts`)

```typescript
export type NetflixStage = 'login' | 'verification' | 'browse' | 'details' | 'watch' | 'unknown';
export type NetflixInputKind = 'email' | 'password' | 'code' | 'search' | 'none';

export interface NetflixContext {
  stage: NetflixStage;
  input_kind: NetflixInputKind;
  has_error: boolean;
  can_submit: boolean;
  focused_title: string | null; // 僅在 stage === 'browse' 時非 null
}

export interface TextInputMessage {
  version: 1;
  type: 'text_input';
  request_id: string;
  text: string;
  submit?: boolean;
}

export interface StateMessage {
  version: 1;
  type: 'state';
  active_app: string;
  focused_tile: string;
  volume: number;
  muted: boolean;
  channel_number: number | null;
  channel_name: string | null;
  status_message: string | null;
  error_message: string | null;
  netflix_context?: NetflixContext | null;
}
```

### 7.3 零機密外洩保證 (Zero-Leakage Assurance)

1. **嚴禁傳輸之機密清單**：
   - 絕無 `value`、字串長度（`length`）、`email`、`password`、`code`、Cookie、Token 或任何 Session Secret。
2. **focused_title 邊界規則**：
   - **僅限 `stage === 'browse'` 允許提取片名**。進入 `details`、`watch` 或其他階段時，`focused_title` 強制設定為 `None`。
   - 片名最大長度 120 字元，超出部分自動截斷，過濾所有 HTML 標籤。

---

## 8. PWA 與 Expo Context Card 互動呈現 (PWA & Expo Context Card UX)

### 8.1 Inline 情境卡與輸入模式

Context Card 採用**非侵入式 Inline 卡片**呈現於遙控器介面頂部或專屬區塊，不強制彈出全頁對話框阻斷 D-Pad 操作：

1. **Email 模式 (`input_kind: 'email'`)**：
   - 鍵盤類型為 `email-address`，關閉自動大寫與自動修正。
   - 卡片提示：「請輸入 Netflix 電子郵件或手機號碼」。
2. **密碼模式 (`input_kind: 'password'`)**：
   - 強制啟用安全遮蔽（`secureTextEntry={true}`）。
   - 卡片提示：「請輸入 Netflix 密碼」。
3. **驗證碼模式 (`input_kind: 'code'`)**：
   - 啟用數字專用鍵盤（`number-pad`）或英數大寫。
   - 卡片提示：「請輸入驗證碼 (OTP)」。
4. **一般化錯誤提示 (Generic Error)**：
   - 當 `has_error === true` 時，卡片以紅色警示邊框顯示：「登入或驗證失敗，請檢查電視畫面後重試」。絕不印出具體密碼錯誤內容或猜測訊息。
5. **送出即清空 (Send-and-Clear) 與 Submit 旗標**：
   - 使用者自 Context Card 點選「送出」時，調用 `sendText(text, submit=true)` / `sendTextInput(text, submit=true)`。
   - 發送後本地 TextInput state 立即清為 `""`。
   - 一般鍵盤輸入則維持 `submit=false`，僅聚焦輸入不自動提交。
   - 卡片顯示「等待電視端回應...」暫態，直到接收到下一筆 `netflix_context` 更新。

### 8.2 瀏覽模式與 Expo TAB 鍵

1. **Browse 模式 (`stage: 'browse'`)**：
   - 卡片顯示：`🎬 目前選取：{focused_title}`。
   - 提供快速導航提示與 OK 播放按鈕。
2. **Expo 補齊 TAB 控制**：
   - Expo 原生遙控器在工具列中補齊 `TAB` 命令發送按鈕，協助使用者在非標準彈窗（如 Profile 切換選單）中切換焦點。

---

## 9. Netflix 軌道與片卡智慧導航 (Rail & Card Navigation)

由後端注入之 `netflix_control.js` 執行幾何與語意導航計算：

1. **同軌道橫向切換 (Horizontal Same-Rail)**：
   - 僅在當前活動的 Rail 容器（`.rowContainer`, `.lolomoRow`）內部搜尋可見片卡（`.title-card`, `.slider-item`）。
   - 依據 DOM 座標選取左右相鄰卡片進行聚焦與置中捲動（`scrollIntoView`）。
2. **跨軌道縱向切換 (Vertical Adjacent-Rail)**：
   - 尋找 Y 軸相鄰之上一列或下一列軌道。
   - 計算該列所有片卡中心點，選取與當前片卡 X 軸距離最小（最接近垂直對齊）之卡片進行聚焦。
3. **忽略雜訊元素**：
   - 完全忽略頁面頂部 Header 導航按鈕、滾動箭頭（`.handle-prev`, `.handle-next`）、以及展開中的預覽浮層（Preview Popover），避免焦點迷失。

---

## 10. OK 直接播放與 Type+Submit 複合動作 (Direct-Play & Type+Submit Composites)

### 10.1 OK 直接播放複合動作 (OK Direct-Play Composite Action)

當使用者於 `stage: 'browse'` 在片卡上按下 `OK` 鍵時，由 runtime 執行非同步直接播放複合動作：

```
                    [ User Presses OK in Browse Mode ]
                                    |
                                    v
                 +--------------------------------------+
                 | 1. 檢查當前片卡或浮層內是否有可見    |
                 |    Play / Resume 按鈕?               |
                 +--------------------------------------+
                               /          \
                       (YES)  /            \ (NO)
                             v              v
            +--------------------+    +----------------------------------------+
            | 立即點選 Play/Resume|    | 2. 點選片卡 (Click Card)               |
            +--------------------+    +----------------------------------------+
                                                        |
                                                        v
                                      +----------------------------------------+
                                      | 3. Bounded 等待 (最大 1200ms)           |
                                      |    等待詳情層 Visible Play/Resume 出現 |
                                      +----------------------------------------+
                                                        |
                                            +-----------+-----------+
                                            |                       |
                                       (Found Play)             (Timeout)
                                            |                       |
                                            v                       v
                              +--------------------+    +----------------------+
                              | 4. 點選 Detail 播放|    | 5. 終止動作 (No Retry)|
                              |    完成播放切換    |    |    回傳穩定錯誤代碼  |
                              +--------------------+    +----------------------+
```

1. **嚴禁拼裝 Watch URL**：禁止從 DOM 抓取 ID 自行透過 CDP 導航至 `https://www.netflix.com/watch/...`。
2. **單次 Side Effect Chain 與無重試**：若點選卡片後在 1200ms 內未出現播放按鈕，或動作結果未知（Outcome Unknown），**嚴禁自動重新發送或重試**。

### 10.2 Type+Submit 複合動作 (Type+Submit Composite Action)

當接收到 `TextInputMessage(text=..., submit=True)` 時：
1. 控制器定位目前已聚焦或主要的可編輯欄位（Email / Password / Code）。
2. 透過 CDP `Input.insertText` 將文字寫入。
3. 立即尋找並點選可見之主要送出按鈕（如「下一步」、「登入」、「驗證」）。
4. 在同一 short transaction 內進行 bounded settle（上限 800ms~1200ms），等待新頁面 DOM 穩定。
5. 提取新頁面之 `NetflixContext` 回傳；若 outcome unknown 則直接終止，不重複重送。

---

## 11. BACK 與 PLAY_PAUSE 語義控制 (BACK & PLAY_PAUSE Handling)

1. **BACK 鍵**：
   - `stage === 'watch'`：點選播放器返回按鈕（`.button-nfplayerBack`）或執行 `history.back()`，等待返回首頁並將 context 更新為 `stage: 'browse'`。
   - `stage === 'details'`：點選關閉按鈕（`.close-button`）或發送 `Escape` 關閉詳情層。
   - `stage === 'browse'`：執行標準電視 BACK 行為。
2. **PLAY_PAUSE 鍵**：
   - 透過 CDP 確認當前 document 中存在 `<video>` 且 `readyState >= 2`。
   - 若正在播放則呼叫 `pause()`，暫停中則呼叫 `play()`。

---

## 12. 錯誤處理、安全性與隱私架構 (Errors, Security & Privacy)

1. **CDP 網路邊界**：CDP 連線僅綁定於 `127.0.0.1` 隨機分配埠號，僅控制 FreeTV 自行啟動並持有的 Chrome Process，動作完畢立即關閉連線。
2. **DOM 改版降級策略**：若 Netflix DOM 改版導致選擇器失效，控制程式回傳具名錯誤代碼，將 stage 設為 `unknown`，系統自動降級為標準 D-Pad 導航，不導致系統崩潰。
3. **機密資料零留存**：文字輸入一律透過 CDP `Input.insertText` 注入聚焦欄位，不讀回、不記錄、不廣播任何使用者輸入內容。

---

## 13. 受影響檔案清單 (Affected Files)

| 模組 / 子系統 | 檔案路徑 | 修改性質與責任 |
| :--- | :--- | :--- |
| **Backend Protocol** | `backend/app/protocol.py` | 定義 `NetflixStage`, `NetflixInputKind`, `NetflixContext`，更新 `TextInputMessage` (加 `submit`) 與 `StateMessage` |
| **Backend State** | `backend/app/state.py` | 全域狀態維護 `netflix_context`，支援重設與清空 |
| **Backend Commands Ports** | `backend/app/commands/ports.py` | 更新 `ApplicationPort` 介面簽章以回傳 `NetflixContext \| None`，支援 `type_text(text, submit)` |
| **Backend Command Bus** | `backend/app/commands/bus.py` | 擁有唯一 StateStore 更新權與廣播權，處理 context 廣播與離開時清空 |
| **Backend Chrome Policy** | `backend/app/applications/chrome_policy.py` | 定義 `--disable-notifications` 與 `--deny-permission-prompts` 啟動參數 |
| **Backend Netflix Driver** | `backend/app/applications/netflix_page.py` | 實作短連線狀態提取、導航、OK 直接播放與 Type+Submit 複合動作 |
| **Backend Netflix JS** | `backend/app/applications/netflix_control.js` | 注入之 DOM 幾何導航、安全 Context 提取與播放輔助腳本 |
| **Backend Manager** | `backend/app/applications/manager.py` | 以 `--app=<url>` 啟動獨立面板 Netflix（無 positional URL），轉交命令並回傳 context，管理全螢幕探測 |
| **Backend YouTube Driver** | `backend/app/applications/youtube_fullscreen.py` | **[新檔]** 實作 `YoutubeFullscreenController`（1s 探測、單次手勢全螢幕、無重試） |
| **Backend Tests** | `backend/tests/test_netflix_page.py` | Netflix 狀態映射、導航、OK 複合動作與 Type+Submit 單元測試 |
| **Backend Tests** | `backend/tests/test_command_bus.py` | 驗證 CommandBus state ownership、context 廣播與非 Netflix 離開清空 |
| **Backend Tests** | `backend/tests/test_applications.py` | 驗證 `_chrome_desktop_args` 包含 `--app=...` 且無額外 positional URL、視窗追蹤與生命週期 |
| **Backend Tests** | `backend/tests/test_chrome_policy.py` | TV Chrome 啟動參數與 Profile 隔離性測試 (`chrome-tv-profile`, `chrome-netflix-profile`) |
| **Backend Tests** | `backend/tests/test_youtube_fullscreen.py` | **[新檔]** YouTube 全螢幕路由 (`#/watch?v=`)、單次手勢觸發與無重試測試 |
| **Frontend Types** | `frontend/src/types/protocol.ts` | 定義 PWA 端 `NetflixContext`, `TextInputMessage.submit` 與更新 `StateMessage` |
| **Frontend Socket** | `frontend/src/api/controllerSocket.ts` | `sendText(text, submit?)` 支援可選 `submit` 參數 |
| **Frontend Socket Test** | `frontend/src/api/controllerSocket.test.ts` | 測試 `sendText` 序列化包含 `submit` 旗標 |
| **Frontend Remote** | `frontend/src/remote/RemotePage.tsx` | 實作 PWA Inline Context Card、輸入模式與片名顯示 |
| **Frontend Remote Test** | `frontend/src/remote/RemotePage.test.tsx` | PWA 遙控器 Context Card 狀態切換、安全輸入與 submit 測試 |
| **Mobile Types** | `mobile/src/types/protocol.ts` | 定義 Expo 端 `NetflixContext`, `TextInputMessage.submit` 與更新 `StateMessage` |
| **Mobile Socket** | `mobile/src/api/controllerSocket.ts` | `sendTextInput(text, submit?)` 支援可選 `submit` 參數 |
| **Mobile Socket Test** | `mobile/src/api/controllerSocket.test.ts` | 測試 `sendTextInput` 序列化包含 `submit` 旗標 |
| **Mobile Remote** | `mobile/src/screens/RemoteScreen.tsx` | 實作 Expo Inline Context Card、TAB 鍵控制與輸入卡片 |
| **Mobile Modal** | `mobile/src/components/TextInputModal.tsx` | 支援 email / password / code 模式切換與送出即清空 |
| **Mobile Remote Test** | `mobile/src/screens/RemoteScreen.test.tsx` | Expo 遙控器 Context Card 互動測試 |

---

## 14. 自動化測試計畫 (Automated Tests)

### 14.1 後端測試計畫 (Backend Pytest)

1. **Netflix 獨立面板啟動參數測試 (`test_applications.py`)**：
   - 驗證 `_chrome_desktop_args` 啟動引數陣列中包含 `f"--app={url}"`。
   - 驗證啟動引數陣列結尾**絕不包含多餘的 positional url**。
   - 驗證包含 `--user-data-dir=config/chrome-netflix-profile`、`--start-fullscreen`、`--disable-notifications` 與 `--deny-permission-prompts`。
2. **狀態映射與列舉測試 (`test_netflix_page.py`)**：
   - 驗證登入階段 email / password 輸入框分別映射為對應 `input_kind`。
   - 驗證 OTP 驗證碼頁面映射為 `stage: VERIFICATION, input_kind: CODE`。
   - 驗證片單瀏覽頁面提取 `focused_title`，且長度 <= 120 字元；驗證非 browse 階段 `focused_title` 必為 `None`。
   - 驗證任何情況下 `NetflixContext` 絕不包含輸入值、長度或密碼字串。
3. **OK 直接播放與 Type+Submit 測試 (`test_netflix_page.py`)**：
   - 模擬卡片已有 Play 按鈕：驗證直接觸發 Play Click。
   - 模擬卡片無 Play 按鈕：驗證觸發 Card Click 並在 Bounded Settle 內等待 Detail Play 出現後點選。
   - 測試 `type_text(text, submit=True)`：驗證依序完成文字輸入、點選送出按鈕並回傳新頁面 context；驗證逾時不重試。
4. **CommandBus 狀態與廣播測試 (`test_command_bus.py`)**：
   - 驗證每次 Netflix 指令執行後，CommandBus 正確更新 `netflix_context` 並發送 StateMessage。
   - 驗證按下 HOME 或開啟其他 App 時，`netflix_context` 立即更新為 `None` 並廣播。
5. **YouTube 全螢幕控制器測試 (`test_youtube_fullscreen.py`)**：
   - 驗證 `/watch?v=` 與 `#/watch?v=` 均能正確辨識為 watch 路由。
   - 驗證在 `video.readyState >= 2` 時僅執行一次 `userGesture=true` 之全螢幕指令。
   - 驗證相同 `video_id` 連續探測時不重複觸發；驗證發送後不執行任何次要 fallback。
6. **啟動參數與 Profile 隔離測試 (`test_chrome_policy.py`)**：
   - 驗證 TV Chrome 啟動參數包含 `--disable-notifications` 與 `--deny-permission-prompts`。
   - 驗證沿用專用設定檔目錄 `config/chrome-tv-profile` 與 `config/chrome-netflix-profile`，不碰日常 Chrome 目錄。

### 14.2 前端與行動端測試計畫 (Frontend & Mobile Jest)

1. **ControllerSocket 序列化測試 (`controllerSocket.test.ts`)**：
   - 驗證 `sendText("abc", true)` 產生 `{ type: 'text_input', text: 'abc', submit: true }`。
   - 驗證 `sendText("abc")` 產生 `{ type: 'text_input', text: 'abc', submit: false }` 或無 submit。
2. **Context Card 渲染與互動測試 (`RemotePage.test.tsx`, `RemoteScreen.test.tsx`)**：
   - 接收 `input_kind: 'email'` 時，文字輸入框啟用 email-address 鍵盤且無遮蔽。
   - 接收 `input_kind: 'password'` 時，文字輸入框強制啟用 `secureTextEntry`。
   - 接收 `input_kind: 'code'` 時，啟用數字專用鍵盤。
   - 測試送出後立即呼叫清空 callback，確保輸入文字不滯留於元件狀態。
   - 測試收到 `netflix_context: null` 時 Context Card 立即卸載。

---

## 15. 真實實機驗收規範 (Real Chrome / PWA / Expo Acceptance Criteria)

| 驗收項目 | 測試環境 | 驗收步驟 | 預期通過標準 (Pass Criteria) |
| :--- | :--- | :--- | :--- |
| **Netflix 獨立面板驗收** | 電視端 Chrome | 1. 於電視端點選啟動 Netflix。<br>2. 檢查進程命令列與視窗外觀。 | Command Line 明確包含 `--app=https://www.netflix.com` 且無 positional URL；電視畫面上**絕無分頁列 (Tab Bar)、網址列 (Omnibox) 與工具列**，呈現純淨獨立面板視窗。 |
| **Widevine 與登入保留** | 電視端 Chrome | 1. 開啟 Netflix 登入帳號並播放受保護影片。<br>2. 關閉後再次開啟。 | Widevine L3 解密正常播放，高畫質視訊不卡頓；專用 profile 正確保留登入會話。 |
| **通知阻擋驗收** | 電視端 Chrome | 1. 啟動 TV YouTube 與 Netflix。<br>2. 導航至要求推播權限之網站。 | 絕無任何「允許通知」或權限彈窗遮蔽電視畫面。 |
| **YouTube 自動全螢幕** | 電視端 Chrome + YouTube | 1. 選取並開啟任一 YouTube 影片（含 `#/watch?v=`）。<br>2. 觀察影片載入過程。 | 影片載入完成後 1 秒內自動切入全螢幕播放；按 Esc 退出後同影片不再強制拉回。 |
| **Netflix 登入同步** | 電視 Chrome + PWA / Expo | 1. 電視開啟未登入之 Netflix。<br>2. 觀察手機遙控器畫面。 | 手機自動浮現 Email 情境卡；送出後自動切換為 Password 卡片（安全遮蔽）。 |
| **Netflix 片單導航** | 電視 Chrome + PWA / Expo | 1. 進入 Netflix 首頁 Browse 模式。<br>2. 操作 D-Pad 上下左右。 | 手機 Context Card 即時顯示當前聚焦片名；上下鍵平滑切換至相鄰軌道最近片卡。 |
| **OK 一鍵直接播放** | 電視 Chrome + 遙控器 | 1. 在 Browse 模式選中任一影片。<br>2. 按下遙控器 OK 鍵。 | 順暢啟動播放並進入播放器介面，無卡頓與重複點選。 |
| **切換與退出清空** | 電視 Chrome + PWA / Expo | 1. 從 Netflix 按 HOME 或切換至其他應用。 | 手機端 Context Card 立即消失，無殘留狀態或殘留文字。 |

---

## 16. 範圍外項目 (Out of Scope)

1. **Android TV Sideload / APK 模擬**：本專案不側載 Android APK，亦不安裝/維護 Android 模擬器或虛擬機環境。
2. **客製自製 WebView2 / Electron 殼層**：不自建客製化 WebView2 或 Electron 瀏覽器外殼，避免缺少 Google VMP 簽章造成 DRM 播放失敗。
3. **DRM / Widevine 解密與繞過 (DRM Bypass)**：本系統僅為標準瀏覽器之電視輔助與自動化介面，絕不涉及任何串流解密、金鑰提取或側錄行為。
4. **憑證持久化儲存 (Credential Persistence)**：後端與手機端絕不代存使用者的 Netflix 帳號密碼或 Session Cookie。
5. **通用網頁瀏覽器自動化 (Generic Web Automation)**：本規格僅深度適配客廳核心串流情境，不提供通用 DOM 爬蟲或自動化框架。
6. **永久 DOM 結構相容性承諾 (Permanent DOM Guarantee)**：串流平台官方前端改版時，系統以安全降級至通用 D-Pad 遙控器為防線，不保證所有私有 CSS 選擇器永久不變。
