# Architecture

## Process boundary

```mermaid
flowchart LR
  PWA["/remote PWA"] -->|LAN HTTP(S) / WS(S)| API[FastAPI controller]
  Expo[Expo native Remote] -->|LAN HTTPS / WSS| API
  TV[Local TV Launcher] -->|loopback HTTP(S) / WS(S)| API
  API --> Bus[CommandBus]
  Bus --> Apps[ApplicationManager]
  Bus --> Player[MpvController]
  Bus --> Input[Platform input adapter]
  Bus --> Volume[Platform volume adapter]
  Apps --> Shell["Netflix standalone Chrome app window<br/>--app=&lt;url&gt;"]
  Apps -->|typed Netflix command/text| Page[NetflixPageController]
  Page -->|fresh short-lived CDP on 127.0.0.1| NetflixDOM[Netflix DOM runtime]
  NetflixDOM -->|safe NetflixContext| Bus
  Apps --> Fullscreen[YoutubeFullscreenController]
  Fullscreen -->|bounded per-video short CDP| YoutubeDOM[Owned YouTube/News Chrome]
  Bus -->|authoritative state| PWA
  Bus -->|authoritative state| Expo
  Player --> MPV[mpv JSON IPC]
```

FastAPI is the sole transport server. The React TV Launcher, `/remote` PWA, and Expo Remote consume server state; none calls Windows APIs, launches applications, or receives a general CDP capability. Every control source becomes one strict version 1 protocol message and flows through `CommandBus`.

## Native Remote

`mobile/` is an Expo/React Native client, not a second controller. It pairs only through the existing numeric-IP HTTPS endpoint, then sends the same protocol messages through `wss://<controller-IP>:<port>/ws/remote`. Its native WebSocket implementation supplies the matching `origin` request header required by the controller. Pairing tokens are stored separately from device metadata in device-bound Expo SecureStore; a migration removes legacy plaintext metadata tokens.

QR pairing is the primary endpoint-discovery path. A code-only QR is never assigned an invented address: the user must supply a numeric LAN IP. The app intentionally does not perform arbitrary subnet scans. Android's generated native network policy disallows cleartext and trusts only the system and user CA stores so the manually trusted controller CA works without weakening TLS for the app.

## Backend modules

| Module | Responsibility |
|---|---|
| `app/protocol.py` | Versioned, strict Pydantic WebSocket models and command whitelist. |
| `app/websocket/` | Authenticated connection registry, acknowledgements, and state fan-out. |
| `app/security/` | Pairing codes, salted token store, and the per-user local CA/IP-SAN TLS materials. |
| `app/commands/bus.py` | Sole owner of `ControllerState`, including Netflix context update/invalidation and state/error outcomes. |
| `app/applications/manager.py` | Tracks owned process/PID/HWND lifecycle, standalone Netflix shell, and YouTube/News fullscreen-controller lifecycle. |
| `app/applications/netflix_page.py` | Discovers the unique Netflix target and performs bounded, short-lived localhost CDP transactions returning strict context. |
| `app/applications/netflix_control.js` | Fixed async DOM runtime for safe context, rail navigation, bounded direct play, submit, BACK, and ready-video playback. |
| `app/applications/youtube_fullscreen.py` | Bounded localhost probe that requests fullscreen at most once per YouTube video identity. |
| `app/player/channels.py` | Validates and selects enabled, ordered channels. |
| `app/player/mpv.py` | Starts mpv and controls it over JSON IPC (named pipe on Windows, Unix socket elsewhere). |
| `app/system/` | Narrow platform adapters for mouse, Unicode text, windows, sleep, and volume. Windows uses SendInput/Core Audio; macOS/Linux use xdotool/wpctl/pactl/osascript behind the same ports. |
| `app/state.py` | Lock-protected controller state snapshot shared by all transports. |
| `app/controller.py` | Composition root that injects platform adapters and coordinates cleanup. |

## Command flow

1. A Remote loads `<scheme>://<controller-literal-IP>:<port>/remote` using the configured `server.transport`; the server rejects arbitrary Host names and mismatched browser Origins. Plaintext LAN access is rejected only in HTTPS mode.
2. The Remote connects with `ws://` or `wss://` matching that transport, has bounded pre-authentication admission, and must authenticate with a valid token before any command, pointer, or text-input message.
3. `CommandBus` routes through `ApplicationPort`. HOME remains the separate `return_home()` lifecycle branch.
4. `ApplicationManager` returns strict Netflix context from `NetflixPageController`; Browser BACK and YouTube/News Windows-input behavior remain separate. The manager never receives `StateStore` or a broadcast capability.
5. `CommandBus` alone writes returned context to `StateStore`. Netflix commands/text update it; HOME, another app, rollback, and failure clear it.
6. `ConnectionRegistry` broadcasts authoritative state only for `state_changed` outcomes, after filtering invalid sessions.
7. The source Remote receives one `ack` per request ID. PWA/Expo submit uses the existing version 1 `text_input` with `submit=true`, not a new command type.

The TV socket accepts only `CommandMessage`, requires both a loopback client address and the exact local TV Origin, and cannot pair, send text, or move the pointer. Production startup uses the configured transport; loopback plaintext remains available for the development proxy.

## Netflix page adapter

Netflix starts in a controller-owned Chrome **app window** with exactly one `--app=<configured HTTPS Netflix URL>`, no positional Netflix URL, and therefore no normal tab strip or omnibox. This is still desktop Chrome—not a native/Android Netflix app. It uses `config/chrome-netflix-profile`, `--start-fullscreen`, `--disable-extensions`, both permission-prompt suppression flags, `--remote-debugging-address=127.0.0.1`, and a reserved port. It does not load the YouTube/News AdBlock extension. New and reused windows call idempotent `initialize()`; failure closes only a new owned window or re-minimizes a reused one.

Each transaction performs a fresh `GET http://127.0.0.1:<port>/json/list`, requires one top-level `netflix.com` page without an opener, validates a `ws://127.0.0.1:<port>` debugger URL, opens one WebSocket, verifies/injects runtime version `1`, performs its bounded operation, and closes. No CDP socket, DOM node, or rectangle persists between transactions.

The runtime returns a strict frozen `NetflixContext`: `stage`, `input_kind`, boolean `has_error`, boolean `can_submit`, and browse-only `focused_title` (at most 120 characters). Extra fields are rejected. Values, lengths, emails, passwords, codes, cookies, tokens, session data, request bodies, MediaKeys, Widevine exchanges, and licensing traffic are never read into context, logs, acknowledgements, or state.

Visible title cards are grouped into rails. Left/Right stays in one rail; Up/Down chooses the nearest-X card in the adjacent rail and excludes headers, slider handles, and preview controls. OK clicks one visible card-contained or newly opened detail Play/Resume control without synthesizing a watch URL. BACK prefers Netflix's player back control; PLAY_PAUSE requires `readyState >= 2`. Type+submit focuses one editable field, sends one `Input.insertText`, clicks one primary action, and bounded-settles context.

Only pre-action discovery/version/injection and explicitly idempotent initialization may retry. After insert/click/BACK/playback/submit is sent, any lost or invalid acknowledgement is outcome-unknown and never replays the side effect. Netflix never falls back to SendInput, coordinates, another tab, or another Chrome process.

Netflix DOM compatibility is necessarily bounded: a site redesign can require runtime/test updates. Credentialed browse/direct-play acceptance additionally requires an externally provided authorized account. The controller does not provision, save, or expose credentials and does not bypass DRM.

## YouTube/News fullscreen lifecycle

YouTube and News use controller-owned fullscreen Chrome with `config/chrome-tv-profile`, localhost-only debugging, store AdBlock, `--disable-notifications`, and `--deny-permission-prompts`. After the owned PID/HWND and AdBlock attach succeed, `ApplicationManager` starts one `YoutubeFullscreenController` for that debug port. HOME, another app, replacement, launch rollback, desktop exit, and shutdown await `stop()` before disposing the process.

The controller performs a bounded probe about once per second. Each inspect/fullscreen operation resolves the unique top-level YouTube target through `127.0.0.1`, opens a short CDP socket, and closes it on leaving the async context. A ready video that is not fullscreen receives one `Runtime.evaluate` with `userGesture=true`; its video identity is marked before send. A lost acknowledgement is never retried. Escape therefore remains effective for that identity across later probes, while a new watch/hash-watch/shorts/live identity can request fullscreen once.

## Ownership and Home

`ApplicationManager` creates and records each browser child process. `HOME` calls `ApplicationManager.return_home()`: it closes controller-owned YouTube/News children, minimizes the specific still-owned Netflix or Browser window when applicable, and restores the window titled `我的電視`.
HOME never enters Netflix history or the DOM runtime.
The manager never searches for or terminates arbitrary Chrome, Brave, Edge, or mpv processes.

## State model

`ControllerState` contains:

- `active_app`: `launcher`, `youtube`, `netflix`, `live_tv`, or `browser`.
- `focused_tile`: launcher focus source of truth.
- `volume` and `muted`.
- `channel_number` and `channel_name` when Live TV is active.
- `error_message` and transient `status_message` for explicit UI feedback.
- `netflix_context`: strict safe context while Netflix is active; `null` after HOME, another app, rollback, or failure.

Each connected, still-valid paired Remote receives snapshots after state changes, so multiple remotes converge on the same state. Revoked, evicted, and expired sessions are removed before state fan-out; an authenticated socket is also closed when its token expires.

## Failure containment

Browser lookup, process launch, Netflix target selection/runtime validation, mpv IPC, volume access, named-pipe input, and Windows UI automation are behind small adapters. The production composition root uses concrete implementations; tests inject fakes. Dependency failure becomes a typed `CommandExecutionError` and a displayed state error instead of crashing the controller. Deterministic Netflix target/DOM errors do not retry, and outcome-unknown side effects are never replayed.

## Remote transport security

Default `server.transport` is `"http"`: the controller accepts plaintext LAN Remote traffic at the controller's literal LAN IP with pairing-token auth and Host/Origin checks. The mDNS advertiser starts only in HTTPS mode and publishes an `https_port` TXT record for future discovery clients. The current native app pairs through the TV QR code or a manually entered numeric IP; it does not yet browse mDNS advertisements.

Set `"transport": "https"` to restore encrypted Remote. In that mode `start.ps1` generates or reuses a CA under ignored `config\tls`, refreshes its leaf certificate when the controller IP changes, and starts Uvicorn with that certificate and key. The CA uses a DER `.cer` file so Windows and mobile OS certificate installers can consume it. It must be trusted separately on the TV Windows user and every Remote phone; the script prints its SHA-256 fingerprint for an out-of-band comparison.

## Extension points

Future ESP32, HDMI-CEC, keyboard, or voice transports must only translate their input to `CommandMessage` and call `CommandBus`. They must not directly import application managers, subprocess, or Windows APIs. This preserves the same authorization and state synchronization boundary for every future input source.
