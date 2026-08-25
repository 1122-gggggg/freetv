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
  Bus --> Input[Windows input adapter]
  Bus --> Volume[Windows volume adapter]
  Apps --> Owned[Controller-owned browser windows]
  Apps -->|typed Netflix action| Page[NetflixPageController]
  Page -->|short-lived CDP on 127.0.0.1| NetflixDOM[Netflix DOM in owned Chrome]
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
| `app/commands/bus.py` | Central command routing, state/error outcome, and launcher focus transitions. |
| `app/applications/manager.py` | Tracks owned child processes/windows, maps Netflix commands to typed page actions, and retains HOME ownership. |
| `app/applications/netflix_page.py` | Discovers the unique Netflix target and performs bounded, short-lived localhost CDP transactions. |
| `app/applications/netflix_control.js` | Versioned fixed DOM runtime for visible candidates, semantic focus, navigation, BACK, and playback. |
| `app/player/channels.py` | Validates and selects enabled, ordered channels. |
| `app/player/mpv.py` | Starts mpv and controls it over named-pipe JSON IPC. |
| `app/system/` | Narrow Windows adapters for mouse, Unicode text, windows, sleep, and Core Audio volume. |
| `app/state.py` | Lock-protected controller state snapshot shared by all transports. |
| `app/controller.py` | Composition root that injects platform adapters and coordinates cleanup. |

## Command flow

1. A Remote loads `<scheme>://<controller-literal-IP>:<port>/remote` using the configured `server.transport`; the server rejects arbitrary Host names and mismatched browser Origins. Plaintext LAN access is rejected only in HTTPS mode.
2. The Remote connects with `ws://` or `wss://` matching that transport, has bounded pre-authentication admission, and must authenticate with a valid token before any command, pointer, or text-input message.
3. `CommandBus` routes through the unchanged `ApplicationPort.forward_command()` and `type_text()` boundary. HOME remains a separate `return_home()` branch.
4. `ApplicationManager` sends Netflix navigation and text only to `NetflixPageController`. Browser BACK still uses Alt+Left, while YouTube and News retain their Windows input path.
5. The bus updates `StateStore` after the action outcome is known. A stable controller error becomes a failed acknowledgement without changing the active application.
6. `ConnectionRegistry` broadcasts a new `state` message only when an observable state value changed, filtering invalid Remote sessions first.
7. The source Remote receives an `ack` for each request ID.

The TV socket accepts only `CommandMessage`, requires both a loopback client address and the exact local TV Origin, and cannot pair, send text, or move the pointer. Production startup uses the configured transport; loopback plaintext remains available for the development proxy.

## Netflix page adapter

Netflix starts in Google Chrome with `config/chrome-netflix-profile`, `--start-fullscreen`, `--remote-debugging-address=127.0.0.1`, and a reserved local port. It does not load the YouTube/News AdBlock extension. New and reused owned windows run `FOCUS_PRIMARY`; an initialization failure closes only a newly launched owned Netflix window or re-minimizes a reused one before returning to the launcher.

Every command attempt performs a fresh `GET http://127.0.0.1:<port>/json/list`, requires exactly one top-level page with no opener whose URL host is `netflix.com` or a subdomain, and accepts only a `ws://127.0.0.1:<valid-port>` debugger URL. It then opens one WebSocket context, verifies runtime version `1`, injects the local fixed runtime only when missing, executes one typed action against a newly enumerated DOM, and closes the socket. Element references and rectangles never cross commands.

Connection, version-check, and runtime-injection failures occur before an action and may retry once. `FOCUS_PRIMARY` and `FOCUS_EDITABLE` are idempotent and may also retry once. For NAV, FOCUS_NEXT, OK, BACK, PLAY_PAUSE, or `Input.insertText`, a successful WebSocket send followed by a lost, malformed, or invalid response is an outcome-unknown failure: the controller returns `netflix_controller_unavailable` without replaying the side effect.

This is a clean cutover. Netflix navigation never falls back to SendInput, Alt+Left, coordinates, another tab, or another Chrome process.
Phones cannot provide JavaScript, selectors, URLs, raw keys, CDP methods, or debugger addresses.
Text is sent only to the focused editable field and is excluded from logs, state, and acknowledgements.
The adapter does not inspect credentials, cookies, requests, MediaKeys, Widevine exchanges, or DRM licensing traffic, and it does not bypass DRM.
Netflix DOM changes can require a tested runtime update; permanent compatibility is not guaranteed.

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

Each connected, still-valid paired Remote receives snapshots after state changes, so multiple remotes converge on the same state. Revoked, evicted, and expired sessions are removed before state fan-out; an authenticated socket is also closed when its token expires.

## Failure containment

Browser lookup, process launch, Netflix target selection/runtime validation, mpv IPC, volume access, named-pipe input, and Windows UI automation are behind small adapters. The production composition root uses concrete implementations; tests inject fakes. Dependency failure becomes a typed `CommandExecutionError` and a displayed state error instead of crashing the controller. Deterministic Netflix target/DOM errors do not retry, and outcome-unknown side effects are never replayed.

## Remote transport security

Default `server.transport` is `"http"`: the controller accepts plaintext LAN Remote traffic at the controller's literal LAN IP with pairing-token auth and Host/Origin checks. The mDNS advertiser starts only in HTTPS mode and publishes an `https_port` TXT record for future discovery clients. The current native app pairs through the TV QR code or a manually entered numeric IP; it does not yet browse mDNS advertisements.

Set `"transport": "https"` to restore encrypted Remote. In that mode `start.ps1` generates or reuses a CA under ignored `config\tls`, refreshes its leaf certificate when the controller IP changes, and starts Uvicorn with that certificate and key. The CA uses a DER `.cer` file so Windows and mobile OS certificate installers can consume it. It must be trusted separately on the TV Windows user and every Remote phone; the script prints its SHA-256 fingerprint for an out-of-band comparison.

## Extension points

Future ESP32, HDMI-CEC, keyboard, or voice transports must only translate their input to `CommandMessage` and call `CommandBus`. They must not directly import application managers, subprocess, or Windows APIs. This preserves the same authorization and state synchronization boundary for every future input source.
