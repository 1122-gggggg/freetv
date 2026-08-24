# PC TV Box

A local Windows 11 controller that turns an HDMI-connected PC into a TV-style launcher. It serves a 10-foot TV interface at `/tv` and a paired phone remote at `/remote`; no cloud service, IPTV discovery/scraping, DRM bypass, custom ad-blocking engines, or arbitrary remote shell/keyboard API is included. YouTube and News ad blocking is provided exclusively by loading the verified Chrome Web Store AdBlock extension (`gighmmpiobklfepjocnamgkkbiglidom`) in an isolated TV Chrome profile.

## Requirements

- Windows 11, signed in as the user who will run the TV controller.
- Python 3.11+ for appliance deployment; Node.js LTS only for frontend development.
- Google Chrome for YouTube and News (launched in fullscreen kiosk mode with store AdBlock in an isolated TV profile).
- Microsoft Edge for Netflix. Windows 11 normally installs it.
- [mpv](https://mpv.io/installation/) for Live TV.
- Laptop/PC on a private LAN. Phone may be on another network if `cloudflared` is installed.
- Native Android builds additionally require Android Studio, its Android SDK, and a JDK. Native iOS builds require macOS/Xcode or an authenticated Expo EAS build account.

## Installation

### Appliance (Release zip)

Download `pc-tv-box.zip` from GitHub Releases, unzip it, then in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

The zip includes a prebuilt `frontend\dist`, so setup needs only Python 3.11+. From a development checkout after `npm run build` in `frontend`, `.\scripts\package.ps1` writes the same zip locally.

### Development (git clone)

Open PowerShell in the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

The setup script creates `.venv`, installs Python dependencies, downloads and verifies the official Chrome Web Store AdBlock extension into `vendor/adblock`, and builds the frontend when `frontend\dist` is missing (requires Node.js LTS). It also creates ignored `config/settings.json`, `config/channels.json`, and `config/news.json` from their examples. Default transport is plain HTTP on the private LAN. HTTPS mode additionally creates a controller-specific local CA plus an IP-address TLS certificate in ignored `config\tls`.

Configure nonstandard executable locations in `config/settings.json`:

```json
{
  "applications": {
    "chrome_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "brave_path": "",
    "edge_path": "",
    "mpv_path": "",
    "browser_path": ""
  }
}
```

Empty browser fields use the standard Windows locations where available. The generic Browser tile falls back to Edge unless `browser_path` is configured.

## Start

```powershell
.\scripts\start.ps1
```

The script starts the controller on port `8765`, waits for `/api/health`, then opens the local TV Launcher in Edge full-screen kiosk mode when Edge is available. If `cloudflared` is on PATH it also starts a Cloudflare quick tunnel and reprints pairing with that HTTPS URL. On the first Windows Firewall prompt, allow the controller only on **Private** networks; do not create port-forwarding rules.

- TV Launcher: `http://127.0.0.1:8765/tv` (or `https://` when `server.transport` is `"https"`)
- Phone Remote: `https://<id>.trycloudflare.com/remote` when the tunnel is up, otherwise `http://<PC-LAN-IP>:8765/remote`
- Health: `http://127.0.0.1:8765/api/health`

Scan the QR printed on the TV. The tunnel hostname changes each restart; rescan after `start.ps1`.

For frontend/backend development:

```powershell
.\scripts\dev.ps1
```

It runs Vite on `http://127.0.0.1:5173` and proxies `/api` and `/ws` to the local backend.

## Pair a phone

1. Open the TV Launcher on the HDMI display.
2. Scan the TV QR (Cloudflare HTTPS when the tunnel is running, otherwise the LAN URL). The QR prefills the 6-digit code.
3. The PWA stores the opaque token in its local storage. The native app stores it in the OS secure store.
4. The Remote reconnects automatically after temporary Wi-Fi or server interruptions.

Pairing codes expire after 10 minutes and can be used once. Five failed attempts from one address pause further attempts for one minute. Use **Forget** on the Remote to remove its local token. Install `cloudflared` (`winget install Cloudflare.cloudflared`) for off-LAN control. Skip the tunnel with `.\scripts\start.ps1 -NoTunnel`.

## Native Remote app

`mobile/` is an Expo/React Native app for Android and iOS. It scans the TV pairing QR code, supports manual numeric-IP pairing, stores Remote tokens in device-bound secure storage, and exposes the same typed Remote controls, touchpad, text input, reconnect, and token-revocation flow as the PWA.

Native Remote is HTTPS-only. Before pairing, set `server.transport` to `"https"` and install and trust the controller CA. Android builds include a network-security configuration that trusts user-installed CAs for this app; iOS still requires enabling full trust for the imported CA. The app deliberately does not scan arbitrary LAN addresses: use the TV QR code or enter the numeric LAN IP printed by `start.ps1`.

For a local Android development build:

```powershell
Push-Location mobile
npm install
npm run android
Pop-Location
```

`npm run android` produces a custom development build, not an Expo Go session, because the local-CA trust configuration is native. Build iOS on macOS with Xcode, or use EAS after authenticating your own Expo account.

## Controls

### TV Launcher

- Arrow keys: choose an application tile.
- Enter: launch selected tile.
- Escape: Back.
- Home: minimize/stop the project-owned active application and return to 我的電視.
- Space: Play/Pause.

The phone Remote exposes a dedicated physical-remote layout with three app keys (YouTube, Netflix, 新聞), D-pad navigation, Back/Home, Channel Up/Down, Volume/Mute, one-touch voice recognition, video search, text input, and a constrained touchpad:

- One-finger drag: bounded relative mouse motion.
- One tap / double tap: left click / double click.
- Two-finger vertical drag: mouse-wheel scrolling.
- Voice & Search: dictation and video search query sent directly to launch YouTube search in kiosk Chrome.
- Text: up to 256 sanitized printable characters, sent as Unicode input to the active application.
The Remote never offers raw key sequences, shell commands, PowerShell commands, file paths, or unrestricted pointer coordinates.

## YouTube, Netflix, News, and Browser

- **YouTube** opens Google Chrome in fullscreen kiosk mode (`--kiosk`) with store AdBlock (`gighmmpiobklfepjocnamgkkbiglidom`) in an isolated TV profile (`config/chrome-tv-profile`).
- **News** opens official YouTube Live news streams in fullscreen kiosk Chrome with AdBlock. Switch streams using Channel Up / Channel Down on the Remote or TV interface.
- **Netflix** opens Edge in a new maximized window at Netflix. Login and DRM remain entirely inside Edge/Widevine; this project does not bypass or automate DRM or credentials.
- **Browser** opens the configured browser start URL. By default it uses Edge when no `browser_path` is specified.

Only a concrete window/process launched by this controller is minimized or terminated. The controller never kills every Chrome, Edge, or mpv process on the machine.

## News channels

Edit ignored `config/news.json` (created automatically from `config/news.example.json`):

```json
[
  {
    "id": "dw-news",
    "number": 1,
    "name": "DW News",
    "url": "https://www.youtube.com/watch?v=DWNewsLiveStream",
    "enabled": true
  }
]
```

News channels are official YouTube Live URLs. Channel Up and Channel Down cycle through enabled entries and wrap around.
## Live TV channels

Edit ignored `config/channels.json`:

```json
[
  {
    "id": "demo-channel",
    "number": 1,
    "name": "Demo Channel",
    "url": "https://example.com/live.m3u8",
    "enabled": true
  }
]
```

Use only streams you are authorized to access. Enabled channels are ordered by `number`; `CHANNEL_UP` and `CHANNEL_DOWN` skip disabled entries and wrap around. mpv launches fullscreen with a local named-pipe JSON IPC endpoint. If mpv is missing or crashes, the controller remains running and returns a visible error to TV/Remote state.

## Autostart

Install a per-user scheduled task after verifying normal startup:

```powershell
.\scripts\install-autostart.ps1
```

Remove it with:

```powershell
.\scripts\install-autostart.ps1 -Remove
```

The script changes only the current user's Task Scheduler entry; it does not install a Session-0 Windows service or modify system-wide startup settings.

## Verification

Backend:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -c backend\pyproject.toml backend\tests
```

Frontend:

```powershell
Push-Location frontend
npm run lint
npm run build
npm test
Pop-Location
```

Native mobile:

```powershell
Push-Location mobile
npm test -- --runInBand
npm run typecheck
npx expo export --platform android --output-dir dist
npx expo prebuild --platform android --no-install
Pop-Location
```

Integration smoke test (against an active `start.ps1 -NoBrowser` instance):

```powershell
.\.venv\Scripts\python.exe scripts\integration-smoke.py
```

## Troubleshooting

| Symptom | Action |
|---|---|
| Phone cannot open `/remote` | Same LAN: use the printed numeric IP. Off-LAN: install `cloudflared`, restart `start.ps1`, and rescan the new trycloudflare QR. Do not port-forward 8765. |
| Browser warns about the controller certificate | HTTPS mode only: import `config\tls\pc-tv-box-local-ca.cer` into **Current User → Trusted Root Certification Authorities**. On the phone, transfer and trust the same CA certificate, verifying the fingerprint printed by `start.ps1`. |
| Pairing code rejected | Read the current TV code again; it expires after 10 minutes and becomes invalid after a successful pairing. |
| Brave/Edge unavailable | Confirm the path in `config/settings.json`, then restart the controller. |
| Live TV error | Install mpv, set `applications.mpv_path` if needed, and validate your channel URL and authorization. |
| TV Launcher does not foreground on Home | Keep the 我的電視 tab/window open. The launcher title is used to restore its specific browser window. |
| Phone cannot install PWA | A trusted HTTPS controller origin is required for service workers and install prompts. HTTP mode serves Remote as a normal web page. |
| Native Remote cannot connect | Native app is HTTPS-only. Set `server.transport` to `"https"`, install the controller CA as an app CA on Android or enable full trust on iOS, then confirm the numeric IP matches the QR code or `start.ps1` output. Native Remote does not accept PC names. |

## Security

- Default transport is local HTTP. Off-LAN phones use a Cloudflare HTTPS origin written by `start.ps1`. Pairing code, token auth, Host/Origin checks, 10s auth timeout, and rate limits stay. Do not expose port `8765` on the router.
- In HTTPS mode, state-changing Remote traffic is accepted only through `https://<controller-literal-IP>:<port>` and `wss://<controller-literal-IP>:<port>`, with matching browser Host/Origin; arbitrary hostnames and missing browser Origins are rejected.
- Pairing code display is loopback-only; the unauthenticated TV WebSocket additionally requires the exact local launcher Origin.
- In HTTPS mode the per-user CA signs certificates only for the controller's loopback and current literal IP addresses. Its private key and the token store remain under ignored `config\`.
- Remote sockets must authenticate within 10 seconds. Production launch limits concurrent work, pending pre-authentication sockets, and WebSocket message size.
- Tokens are random, stored only as salted PBKDF2 hashes on PC, and are never logged. Expired, revoked, or evicted Remote sessions are closed and receive no further state.
- A remote can use **Forget** to revoke its persisted token at the controller, immediately closing its paired WebSocket session. Pair it again from the TV code to reconnect.
- Input is validated with versioned Pydantic protocol models at the transport boundary.
- Browser/mpv paths and URLs come only from local typed configuration; subprocess calls use argument arrays, never shell strings.
- The controller binds only to `0.0.0.0` for paired LAN remotes; `scripts/start.ps1` rejects another server host. Do not expose port `8765` to the internet or configure router port forwarding.

## Known limitations

- The TV Launcher is a browser window, not a native Windows shell replacement. Configure Windows sign-in/autostart and use fullscreen/maximized browser behavior for the closest appliance flow.
- HTTP mode cannot install the Remote as a PWA (service workers require a secure context). HTTPS mode requires explicit trust of the controller local CA; the certificate contains literal current IP addresses, so `start.ps1` refreshes it after LAN-address changes.
- Native Remote pairing uses QR or a manually entered numeric IP and remains HTTPS-only; mDNS discovery is advertised only in HTTPS mode.
- Native iOS builds require macOS/Xcode or an authenticated Expo EAS account.
- This project launches existing browsers and mpv only; it does not discover/scrape IPTV streams, bypass DRM, or manage account credentials. Ad blocking is limited strictly to loading the verified store AdBlock extension into the isolated TV Chrome profile.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/PROTOCOL.md](docs/PROTOCOL.md), and [docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md) for implementation details.
