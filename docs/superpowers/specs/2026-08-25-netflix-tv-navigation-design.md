# Netflix TV 免滑鼠導航設計

## 目標

在 Windows 11 PC TV Box 上，讓使用者只靠已配對的手機遙控器完成 Netflix 全流程操作：登入（帳號、密碼、下一步、驗證碼、錯誤後重聚焦）、選擇使用者、瀏覽首頁列與片卡、搜尋、開啟詳情、播放、播放／暫停、返回及 HOME。Netflix 沿用專用 Chrome 設定檔 `config/chrome-netflix-profile`，保留既有登入狀態、Chrome Widevine 與受保護內容播放，並以 `--start-fullscreen` 維持真正全螢幕。

本規格同時保證既有 `/remote` PWA 與 `mobile/` Expo 原生手機遙控器；兩者共用現有 wire protocol、方向鍵、`OK`、`BACK`、`PLAY_PAUSE` 與 `text_input`，不新增 wire message。不承諾實體鍵盤、USB／藍牙遙控器或其他輸入裝置。

## 核准決策

1. 採用 **localhost Chrome DevTools 頁面適配器**：後端透過只綁定 `127.0.0.1` 的 CDP 控制專案啟動且追蹤中的 Netflix Chrome 頁面。
2. 不採 Windows 座標／滑鼠模擬；畫面縮放、解析度或 Netflix 版面改動不得轉化為硬編碼座標。
3. 不採 Android TV 模擬器；不新增 Android 執行環境、Netflix APK 或另一套登入／DRM 邊界。
4. 沿用現有 Remote WebSocket、wire message、命令列舉、`CommandBus`、`ApplicationManager` 與 HOME ownership；`/remote` PWA 與 `mobile/` Expo 共用相同能力，手機不取得 CDP 能力。
5. 頁面控制由專用 `NetflixPageController` 負責，使用專案內固定、可稽核的控制程式；不接受手機提供的 JavaScript、selector、URL 或 raw key。

## 架構與資料流

```text
/remote PWA 或 mobile/ Expo 原生手機遙控器
  │ 既有 typed command 或 text_input（最長 256 字；不新增 wire message）
  ▼
Remote WebSocket
  ▼
CommandBus（序列化、驗證、回覆 ack／穩定錯誤）
  ▼
ApplicationManager（Netflix 行程、視窗、設定檔與 HOME ownership）
  ▼
NetflixPageController（只連 localhost CDP、選定 Netflix page target）
  ▼
固定 Netflix 控制程式（每指令確認存在，必要時注入／重建）
  ▼
Netflix DOM／目前頁面的 video
```

兩種手機遙控器的頁面控制指令只有在 DOM 操作完成、確認為方向邊界，或得到明確錯誤後才回覆。`text_input` 只把經既有協定驗證的文字送入目前已聚焦的可編輯欄位；控制器不讀回欄位值。

## 元件責任

### Remote WebSocket

- 維持既有配對、驗證、限流、request ID 與 acknowledgement；`/remote` PWA 與 `mobile/` Expo 使用同一協定。
- 只接收既有白名單命令及 `text_input`；文字長度上限為 256 字，不新增 wire message。
- 不增加通用瀏覽器控制訊息，也不轉送 JavaScript、selector、URL、raw key 或任意 CDP 方法。

### CommandBus

- 保持所有狀態變更命令序列化。
- Netflix 為 active app 時，將 `NAV_UP`、`NAV_DOWN`、`NAV_LEFT`、`NAV_RIGHT`、`OK`、`BACK`、`PLAY_PAUSE` 與文字輸入交給 `ApplicationManager`；`HOME` 仍走既有 HOME 分支。
- Netflix 的上述頁面命令從現有 Windows `SendInput`／`Alt+Left` 路徑乾淨切換至 `NetflixPageController`；同一指令只執行一條路徑，禁止雙重觸發，也禁止 CDP 失敗後 fallback 至 Windows 輸入。
- 將控制器錯誤轉為固定代碼、穩定繁體中文訊息與失敗 ack，不把 CDP、DOM 或例外細節送到手機。

### ApplicationManager

- 以專用 Chrome 設定檔、`--start-fullscreen`、`--remote-debugging-address=127.0.0.1` 與保留的 localhost 隨機埠開啟 Netflix。
- 只持有本專案啟動／追蹤的 Netflix 行程、視窗與 CDP 埠，並把 Netflix 頁面命令轉交 `NetflixPageController`。
- Netflix 的方向、OK、BACK、PLAY_PAUSE 與文字輸入不再呼叫 Windows `SendInput` 或 `Alt+Left`；控制器失敗即回覆錯誤，不重送到舊路徑。
- 保持現有 ownership：`HOME` 只最小化受追蹤且仍屬於該行程的 Netflix 視窗，切回 launcher；不關閉或控制其他 Chrome。
- 不介入請求、Cookie、登入權杖、Widevine、媒體授權或 DRM。

### NetflixPageController

- 每個交給頁面控制器的手機指令都建立一次短 CDP 連線，查詢 `/json/list`，並鎖定專用 CDP 實例中唯一、top-level 且 URL host 為 `netflix.com` 或其子網域的 page target；動作完成後即關閉連線。
- 鎖定 target 後確認固定控制程式的版本／識別標記；缺少或版本不符時才注入。每次動作重新列舉當下 DOM，不沿用前一指令的元素 reference 或矩形。
- 導覽至新 document、重新整理或 execution context 失效時不維持舊 context；下一個指令以新短連線重新選定 target 並重注入。不建立常駐 CDP 連線或事件監聽器。
- Netflix iframe／popup 若不屬於同一個可控 top-level target，或可接受的 top-level target 不唯一，不得 fallback 到其他 page、分頁或視窗，回覆 `netflix_target_unsupported`。
- CDP 連線、target 查詢或注入失敗時只重試整個短連線流程一次；第二次失敗即回傳穩定錯誤。沒有語意候選等確定性操作錯誤不重試。
- 不回傳輸入欄內容；日誌只記錄命令類型、錯誤代碼、頁面類型與非敏感識別，不記錄文字內容。

### 固定 Netflix 控制程式

- 列舉可見且可互動的連結、按鈕、片卡、使用者卡、輸入欄、頁籤及播放器控制；排除隱藏、停用、零面積、視窗外或被覆蓋項目。
- 保存目前焦點的語意資訊與矩形，套用高對比白框及 Netflix 紅色光暈，並以 `scrollIntoView({block: "center", inline: "center"})` 自動置中。
- 只暴露固定動作介面；不執行網路端提供的程式或 selector。

## 焦點與命令語意

### 方向導航

以目前焦點矩形中心為原點，只保留目標方向半平面內的候選元素。排序先考慮主方向距離，再考慮垂直於主方向的中心距離；主軸投影重疊者優先，完全同分時依穩定 DOM 順序決定。這可同時支援首頁橫向片列、列與列之間的上下移動、登入表單、搜尋結果及播放器控制列。

位於有效方向邊界且目前焦點仍存在時，保留焦點並回覆成功，不環繞到另一側。若目前焦點已失效且頁面上沒有可用候選，回覆 `netflix_focus_unavailable`：「找不到可操作的 Netflix 項目，請稍後再試。」

### OK

- 片卡、使用者卡、按鈕、連結與播放器控制：聚焦後觸發其原生 click。
- 帳號、密碼、驗證碼與搜尋欄：聚焦可編輯欄位，不代填、不讀值；後續文字由手機 `text_input` 插入。
- 非互動容器不得用合成座標點擊。

### BACK

優先關閉最上層可見對話框、詳情層或 Netflix overlay；若沒有可關閉的層，才執行該 Netflix page target 的 `history.back()`。不得作用於其他分頁或其他 Chrome 視窗。

### PLAY_PAUSE

只取得目前 Netflix page target、目前 document 中正在顯示的 `video`。若正在播放則 `pause()`，否則 `play()`；不得搜尋或控制其他分頁、背景頁面或其他 Chrome 的 video。沒有目前 video 時回覆 `netflix_video_unavailable`：「目前沒有可播放或暫停的 Netflix 影片。」

### HOME

完全維持現有 `CommandBus → ApplicationManager.return_home()` ownership 行為，不進入 DOM history，也不把 HOME 改造成 Netflix 首頁鍵。

## 頁面狀態與焦點恢復

控制程式為焦點保存語意指紋：元素角色、可存取名稱、Netflix `data-uia` 類型、正規化可見文字、目的路徑類型、所屬列標題及列內相對位置；不保存輸入值。DOM 重建、換頁或返回後，先找語意最接近且可見的元素，再套用焦點樣式並置中。若原項目已不存在，焦點落在當前畫面的主要操作：

1. 登入／驗證畫面的第一個未完成欄位或主要「下一步／登入」操作。
2. 使用者選擇畫面的第一個使用者卡。
3. 首頁／搜尋結果的主要導覽操作或第一張可見片卡。
4. 詳情層的主要播放操作。
5. 播放畫面的主要播放器控制。

登入送出後若 Netflix 顯示驗證錯誤，控制程式辨識可見錯誤訊息並把焦點放回關聯的帳號、密碼或驗證碼欄；使用者可直接從手機修正，不需滑鼠。

## 完整免滑鼠流程

1. 手機按 **Netflix**，專用 Chrome 設定檔以真正全螢幕開啟；已有登入狀態時直接進入使用者選擇或首頁。
2. 未登入時，焦點落在帳號欄；手機送出帳號，方向鍵／OK 到「下一步」。密碼欄與驗證碼欄使用相同流程。提交錯誤時自動重聚焦錯誤欄位。
3. 使用者選擇畫面可用方向鍵移動、OK 選取。
4. 首頁可在導覽項、內容列與片卡間二維移動；焦點持續顯示白框、紅色光暈並自動置中。
5. 搜尋入口以方向鍵／OK 開啟，搜尋欄聚焦後由手機輸入；結果片卡以方向鍵／OK 操作。
6. OK 開啟片卡詳情；詳情內可選主要播放操作。BACK 先關詳情層，再退回前一頁。
7. 播放期間手機 **播放／暫停** 只切換目前影片；BACK 依 Netflix 當前層級返回。
8. 手機 **主畫面** 最小化受追蹤的 Netflix 視窗並顯示 TV launcher；再次開啟 Netflix 時沿用相同設定檔與登入狀態。

## 錯誤處理

| 狀況 | 代碼 | 手機顯示／行為 |
|---|---|---|
| Netflix page target 不存在或 CDP 無法連線，重試一次仍失敗 | `netflix_page_unavailable` | `無法連到 Netflix 控制頁面，請稍後再試。` |
| 固定控制程式注入或版本確認重試一次仍失敗 | `netflix_controller_unavailable` | `無法載入 Netflix 遙控控制，請稍後再試。` |
| Netflix iframe／popup 不在同一可控 top-level target，或 top-level target 不唯一 | `netflix_target_unsupported` | `Netflix 目前畫面不是可控制的主要頁面。` |
| 焦點失效且沒有任何可用候選 | `netflix_focus_unavailable` | `找不到可操作的 Netflix 項目，請稍後再試。` |
| 文字命令時沒有可編輯欄位 | `netflix_input_unavailable` | `找不到可輸入的 Netflix 欄位，請先選取輸入欄。` |
| 播放／暫停時沒有目前可見 video | `netflix_video_unavailable` | `目前沒有可播放或暫停的 Netflix 影片。` |
| 有效方向邊界 | 無錯誤 | 保留焦點並成功 ack。 |

錯誤不得包含 debugger URL、CDP 埠、DOM、selector、輸入文字、Cookie 或 Netflix 回應內容。失敗不應切換 active app，不得退回 Windows 輸入模擬，也不得 fallback 到其他 CDP target。

## 安全邊界

- CDP 僅監聽並連線 `127.0.0.1`，不得使用 LAN 位址、`0.0.0.0` 或透過 Remote WebSocket 暴露。
- 僅以每指令短連線控制 `ApplicationManager` 追蹤之專用 Chrome 中唯一可接受的 top-level `netflix.com` page target；不控制 iframe／popup 的獨立 target、日常 Chrome、YouTube Chrome、其他分頁或任何未擁有視窗。
- 手機不能傳 JavaScript、selector、URL、raw key、CDP method、滑鼠座標或任意瀏覽器動作。
- `text_input` 最長 256 字，沿用既有可列印 Unicode／控制字元清理；只插入目前聚焦的可編輯欄位。
- 密碼、帳號及驗證碼不得由 DOM 讀回、持久化或寫入日誌；ack 與 state 不回傳輸入內容。
- 不修改或攔截 Netflix 請求、回應、Cookie、Service Worker、MediaKey、Widevine、授權交換或 DRM；控制只作用於可見 DOM 與目前 video 的標準播放介面。

## 測試

### 自動化測試

- Chrome 啟動參數包含專用 Netflix 設定檔、`--start-fullscreen`、`--remote-debugging-address=127.0.0.1` 與專用埠；啟動 URL 只允許設定中的 HTTPS Netflix URL，且不含 AdBlock 或其他設定檔。
- 每個頁面控制指令都以短 CDP 連線重新查詢並鎖定唯一 top-level `netflix.com` page target；同時存在 new tab、YouTube、日常 Chrome、獨立 iframe／popup 或多個 Netflix target 時不誤選、不 fallback。
- 每個交給 `NetflixPageController` 的指令都確認固定控制程式版本並重新列舉 DOM；缺少時只注入一次，換頁／execution context 失效後由下一指令重新連線與建立。
- 證明沒有常駐 CDP 連線／事件監聽器；動作後連線關閉，舊 element reference 與矩形不跨指令使用。
- CDP 連線、target 查詢與注入失敗各只重試一次完整短連線流程，第二次回覆對應穩定代碼；無候選等確定性錯誤不重試。
- DOM fixture 覆蓋登入帳號、密碼、下一步、驗證碼、錯誤重聚焦、使用者卡、首頁列／片卡、搜尋、詳情與播放器。
- 幾何導航覆蓋四方向、交錯矩形、被遮蔽／停用元素、同分決策及方向邊界不移動。
- OK 對輸入欄只聚焦、對可點擊項目觸發原生 click；焦點樣式同時有白框與 Netflix 紅色光暈，並要求自動置中。
- DOM 重建及 history 返回後按語意指紋恢復；無原項目時依頁面類型落在主要操作。
- BACK 先關最上層對話框／詳情層，無層時才 history；PLAY_PAUSE 只操作目前 page 的目前 video。
- `CommandBus` 將 Netflix 方向、OK、BACK、PLAY_PAUSE 與文字只送往頁面控制器，不再觸發 Windows `SendInput`／`Alt+Left`，失敗也不 fallback；HOME 仍走既有 ownership 分支。
- 文字 256 字可接受，257 字、控制字元及 JavaScript／selector／URL／raw-key 類型訊息依既有協定拒絕或清理；日誌、ack、state 均不含輸入文字。
- HOME 只最小化受追蹤 Netflix 視窗；未擁有、其他 Chrome 與其他分頁不受影響。
- `/remote` PWA 與 `mobile/` Expo 回歸測試都覆蓋四方向、OK、BACK、PLAY_PAUSE、256 字文字、失敗 ack 與「不新增 wire message」契約。

### Windows 11 實機驗收
以下全流程須分別以 `/remote` PWA 與 `mobile/` Expo 原生手機遙控器完成；平台無關的 PC／CDP 安全檢查只需執行一次。

1. 僅使用已配對手機，從 launcher 開啟 Netflix；確認使用 `config/chrome-netflix-profile`、瀏覽器 UI 不佔畫面且 Netflix 內容覆蓋完整螢幕。
2. 關閉再重開 Netflix，確認專用設定檔的登入狀態保留；日常 Chrome 設定檔與視窗未被使用或控制。
3. 在未登入狀態，不碰滑鼠完成帳號、下一步、密碼、驗證碼及登入；刻意輸入錯誤資料後，焦點回到關聯欄位並可由手機修正。
4. 不碰滑鼠完成使用者選擇；四方向與 OK 均可操作。
5. 首頁各內容列與片卡可上下左右移動；方向邊界保留原焦點，不跳到另一側。
6. 每個焦點都有清楚高對比白框、Netflix 紅色光暈，移動後自動捲動至畫面中央。
7. 不碰滑鼠開啟搜尋、從手機輸入關鍵字、送出並選取結果片卡。
8. 不碰滑鼠開啟片卡詳情、啟動播放；BACK 先關詳情層，無詳情層時才回前頁。
9. 播放中以手機 PLAY_PAUSE 連續完成暫停與恢復；同時存在其他 Chrome／分頁影片時，其播放狀態不變。
10. 在登入、使用者選擇、首頁、搜尋結果、詳情及播放畫面逐一驗證 BACK 與頁面層級一致，且不影響其他視窗。
11. 在換頁、返回、重新整理及 Netflix 動態重建列／片卡後，焦點按語意恢復；原項目消失時落在該畫面主要操作。
12. 按 HOME 後只最小化受追蹤 Netflix 視窗並顯示 launcher；其他 Chrome 保持原狀。再次開啟 Netflix 可恢復既有視窗／登入狀態。
13. 播放一部實際 Widevine 受保護內容，確認影像與聲音正常、真正全螢幕、導航控制未修改請求／Cookie／Widevine／DRM。
14. 從同一 LAN 的另一台裝置確認 CDP 埠無法連入；本機 `127.0.0.1` 控制仍可用。
15. 對 Remote WebSocket 嘗試 JavaScript、selector、URL、raw key、CDP method 與 257 字文字，確認被拒絕且 Netflix／其他 Chrome 未執行任何動作。
16. 檢查後端日誌、手機 ack／state 與錯誤畫面，確認帳號、密碼、驗證碼及輸入欄值均未被讀回或記錄。
17. 中斷 CDP 或造成注入失敗，確認只自動重試一次，之後顯示固定繁體中文錯誤；恢復後下一個指令可重新建立控制程式。
18. 全流程分別使用 `/remote` PWA 與 `mobile/` Expo 原生手機遙控器完成，兩者的方向、OK、BACK、PLAY_PAUSE、文字輸入與錯誤 ack 行為一致；全程不使用滑鼠、實體鍵盤或 USB／藍牙遙控器。
19. 觀察每個頁面控制指令只產生一次 DOM 動作；CDP 失敗時不出現 Windows `SendInput`／`Alt+Left` 的第二次動作，且動作後沒有常駐 CDP 連線或事件監聽器。

## 預期受影響檔案

- `backend/app/applications/netflix_page.py`：`NetflixPageController` 與 localhost CDP 適配器。
- `backend/app/applications/netflix_control.js`：固定、版本化、可稽核的 DOM 控制程式。
- `backend/app/applications/chrome_page.py`：現有登入欄輸入適配器將由 Netflix 專用控制器取代。
- `backend/app/applications/manager.py`：Netflix 控制器組裝、命令轉送、專用設定檔／全螢幕／CDP 與 ownership。
- `backend/app/commands/ports.py`、`backend/app/commands/bus.py`：Netflix 頁面控制介面與 typed command 路由。
- `backend/tests/test_chrome_page.py`、`backend/tests/test_applications.py`、`backend/tests/test_command_bus.py`、`backend/tests/test_protocol_security.py`：頁面適配、生命週期、路由及安全邊界測試。
- `frontend/src/remote/RemotePage.test.tsx`：手機遙控器完整控制面與 256 字輸入契約測試。
- `mobile/src/screens/RemoteScreen.test.tsx`、`mobile/src/api/controllerSocket.test.ts`：Expo 原生遙控器的命令、文字與失敗 ack 協定回歸；既有 UI 與 wire protocol 無需變更。
- `README.md`、`docs/ARCHITECTURE.md`：實作時把過時的 Netflix／Edge 說明修正為專用 Chrome 設定檔、localhost CDP 與頁面控制器架構。

現有 Remote WebSocket 訊息種類、`frontend/src/remote/RemotePage.tsx` 與 `mobile/src/screens/RemoteScreen.tsx` 控制面足以表達本規格；兩種手機 UI 與 wire protocol 均無需變更，只需回歸測試，且本規格不新增網路能力。

## 明確不在範圍

- Windows 座標滑鼠／觸控模擬、任意 Windows 鍵盤事件或失敗時 fallback 至桌面輸入。
- Android TV 模擬器、Netflix APK、Android 原生遙控協定。
- 實體鍵盤、USB／藍牙／紅外線遙控器、遊戲手把或 HDMI-CEC 保證。
- 自動取得、保存、讀回或代填 Netflix 帳號、密碼、驗證碼。
- 繞過地區、方案、同戶裝置、驗證碼、CAPTCHA、Widevine、HDCP 或任何 DRM／Netflix 安全限制。
- 修改網路請求、Cookie、Service Worker、媒體授權、串流 manifest、字幕或畫質策略。
- 控制 Netflix 以外網站、其他 Chrome 設定檔／視窗／分頁，或提供通用網頁自動化 API。
- 保證 Netflix 未來所有 DOM 版本永久相容；相容性以本規格的語意辨識、固定錯誤與實機驗收維持。
