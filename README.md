# PC TV Box

A local controller that turns an HDMI-connected Windows, macOS, or Linux PC into a TV-style launcher. Copy this folder to any computer, run one command, and that machine becomes a set-top box: a 10-foot TV interface at `/tv` and a paired phone remote at `/remote`. No cloud account, IPTV discovery/scraping, DRM bypass, custom ad-blocking engines, or arbitrary remote shell/keyboard API is included. YouTube and News ad blocking is provided exclusively by loading the verified Chrome Web Store AdBlock extension (`gighmmpiobklfepjocnamgkkbiglidom`) in an isolated TV Chrome profile.

## Requirements

- Windows 10/11, macOS, or Linux, signed in as the user who will run the TV controller.
- Python 3.11+ on `PATH` (`python` / `python3`, or the Windows `py` launcher). The Windows installer can install a user-scoped Python through `winget`; macOS/Linux installers fail closed and ask for Python instead of changing the system package manager.
- Google Chrome or Chromium for YouTube/News TV playback and the Netflix standalone app window. Netflix still relies on Chrome/Widevine and the user's normal Netflix authorization.
- [mpv](https://mpv.io/installation/) for Live TV.
- Laptop/PC on a private LAN. Phone may be on another network if `cloudflared` is installed.
- Linux remotes also need `xdotool` or `ydotool` for D-pad/touchpad injection, and `wpctl` or `pactl` for system volume.
- Node.js LTS only if `frontend/dist` is missing (git clones). Release zips already include it.
- Native Android builds additionally require Android Studio, its Android SDK, and a JDK. Native iOS builds require macOS/Xcode or an authenticated Expo EAS build account.

## Installation

### One-click per-user install (recommended)

Download the installer entry for your platform from the latest GitHub Release:

- **Windows 10/11 x64:** download and double-click `FreeTV-Setup.exe`. The per-user installer deploys FreeTV under `%LOCALAPPDATA%\FreeTV`, creates Start Menu and optional desktop shortcuts, enables logon autostart, and starts the fullscreen TV interface. If Python is missing, installation may use `winget` with `--scope user`.
- **macOS/Linux:** download `install.sh`, then run `sh install.sh`. It verifies the release checksum, installs under the current user's application-data directory, creates a user launcher, and starts FreeTV. Python 3.11+, `curl`, and `unzip` must already be available.

The installer never replaces `config`, `.venv`, `vendor`, or `logs` during upgrades. Chrome/Chromium remains required for browser playback; mpv and cloudflared remain optional capabilities rather than silently installed system dependencies.

### Keep running with a laptop lid closed (Windows)

The recommended `FreeTV-Setup.exe` option configures the active Windows power plan automatically: closing the lid does nothing, and automatic sleep and hibernation are disabled on both plugged-in and battery power. Windows may request administrator approval for this power-plan change. To verify or change it manually:

1. Open **Control Panel → Hardware and Sound → Power Options → Choose what closing the lid does**.
2. Confirm **When I close the lid** is **Do nothing** for both **On battery** and **Plugged in**.
3. Open **Settings → System → Power & battery → Screen and sleep** and confirm sleep is **Never**. The display itself may still turn off.

Keep the laptop connected to power and place it where closing the lid does not obstruct cooling vents. Disabling sleep on battery can drain it completely; Windows critical-battery protection still applies.

### Portable folder

Copy this repository or unzip `pc-tv-box.zip` from GitHub Releases, then:

```bash
python freetv.py
```

On macOS/Linux you can also run `sh ./run.sh` (zip extraction may drop the
executable bit). On Windows, `run.cmd` or:

```powershell
py -3 .\freetv.py
```

That single command creates `.venv`, installs Python dependencies, verifies the official AdBlock extension, builds the frontend if needed, writes local config from examples, starts the controller on port `8765`, and opens the TV launcher fullscreen. Useful subcommands:

```bash
python freetv.py setup       # install only
python freetv.py install     # copy to this user's app directory, create launcher, start
python freetv.py start       # start only
python freetv.py doctor      # print Chrome/mpv/Python/OS readiness
python freetv.py autostart   # start at login (Task Scheduler / systemd / launchd)
```

Skip the browser window with `python freetv.py start --no-browser`. Skip Cloudflare with `--no-tunnel`.

## Updates

FreeTV checks GitHub Release metadata in the background. When a newer tagged release contains the exact `pc-tv-box.zip` and `pc-tv-box.zip.sha256` assets, the TV, web Remote, and native Remote receive an update notice through controller state.

Select **立即更新** from a paired client to download and verify the archive. The controller stages it under `config/updates` and leaves the running version untouched. Restart FreeTV once to apply the staged managed files; personal configuration, the virtual environment, extensions, and logs are preserved. Invalid checksums, unsafe ZIP paths, oversized archives, unauthenticated remotes, and concurrent update attempts are rejected.

### Appliance (Release zip, Windows PowerShell)

Download `pc-tv-box.zip` from GitHub Releases, unzip it, enter the extracted
`pc-tv-box` directory, then in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

The zip includes a prebuilt `frontend\dist`, so setup needs Python 3.11+ and network access to install its Python packages. From a development checkout after `npm run build` in `frontend`, `.\scripts\package.ps1` writes the same zip locally.

### Development (git clone)

```bash
python freetv.py setup
```

or, on Windows PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

The setup path selects a qualifying Python 3.11+ runtime, creates `.venv`, installs Python dependencies, downloads and verifies the official Chrome Web Store AdBlock extension into `vendor/adblock`, and builds the frontend when `frontend/dist` is missing (requires Node.js LTS). An existing `.venv` must contain an isolated Python 3.11+ runtime; setup leaves an invalid environment untouched and asks you to remove or rename it manually. It also creates ignored `config/settings.json`, `config/channels.json`, and `config/news.json` from their examples. Default transport is plain HTTP on the private LAN. HTTPS mode additionally creates a controller-specific local CA plus an IP-address TLS certificate in ignored `config/tls`.

Configure nonstandard executable locations in `config/settings.json`:

```json
{
  "applications": {
    "chrome_path": "",
    "brave_path": "",
    "edge_path": "",
    "mpv_path": "",
    "browser_path": ""
  }
}
```

Empty browser fields use the standard OS locations where available (Windows Program Files, `/usr/bin`, `/Applications`). The generic Browser tile falls back to Chrome unless `browser_path` is configured.

## Start

```bash
python freetv.py start
```

Windows PowerShell equivalent: `.\scripts\start.ps1`.

The controller binds port `8765`, waits for `/api/health`, then opens the local TV Launcher fullscreen in Chrome/Chromium when available. Re-running it starts a new controller only if the port is free; it refuses to stop an unrelated listener. If `cloudflared` is on PATH it also starts a Cloudflare quick tunnel and reprints pairing with that HTTPS URL.

- TV Launcher: `<scheme>://127.0.0.1:8765/tv`
- Phone Remote: `https://<id>.trycloudflare.com/remote` when the tunnel is up, otherwise `<scheme>://<PC-LAN-IP>:8765/remote`
- Health: `<scheme>://127.0.0.1:8765/api/health`

Use `http` for the default transport and `https` when `server.transport` is `"https"`. Scan the QR printed on the TV. The tunnel hostname changes each restart; rescan after start.

For frontend/backend development:

```bash
./scripts/dev.ps1
```

It runs Vite on `http://127.0.0.1:5173` and proxies `/api` and `/ws` to the local backend.

## Pair a phone

1. Open the TV Launcher on the HDMI display.
2. Scan the TV QR (Cloudflare HTTPS when the tunnel is running, otherwise the printed `<scheme>://<PC-LAN-IP>:8765/remote`) and enter the 6-digit code (QR prefills it).
3. The PWA stores the opaque token in its local storage. The native app stores it in the OS secure store.
4. The Remote reconnects automatically after temporary Wi-Fi or server interruptions.

Pairing codes expire after 10 minutes and can be used once. Five failed attempts from one address pause further attempts for one minute. Use **Forget** on the Remote to remove its local token. Install `cloudflared` for off-LAN control. Skip the tunnel with `python freetv.py start --no-tunnel`.

## Native Remote app

`mobile/` is an Expo/React Native app for Android and iOS. It scans the TV pairing QR code, supports manual numeric-IP pairing, stores Remote tokens in device-bound secure storage, and exposes the same typed controls and Netflix context card as the PWA. The context card selects safe email/password/verification input modes but never persists field contents.

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

The PWA and Expo Remotes expose three app keys (YouTube, Netflix, 新聞), D-pad navigation, Back/Home, Fullscreen, TAB/下一欄, Channel Up/Down, Volume/Mute, voice search, bounded text input, and a constrained touchpad:

- One-finger drag: bounded relative mouse motion.
- One tap / double tap: left click / double click.
- Two-finger vertical drag: mouse-wheel scrolling.
- Voice & Search: dictation and a bounded query that opens YouTube TV search.
- Text: up to 256 sanitized printable characters. Ordinary keyboard input sends `submit=false`; the Netflix context card can send one type-and-submit operation with `submit=true`.

The Remote never offers raw key sequences, shell commands, PowerShell commands, file paths, browser selectors, JavaScript, or unrestricted pointer coordinates. Local password/code state is cleared when sent or when Netflix context changes; it is not logged or persisted.

## YouTube, Netflix, News, and Browser

- **YouTube** opens controller-owned Google Chrome fullscreen in `config/chrome-tv-profile`, with localhost-only debugging and the verified store AdBlock. A bounded `YoutubeFullscreenController` checks short-lived CDP sessions and requests fullscreen once for each new `/watch`, TV hash-watch, `/shorts`, or `/live` identity. Escape is respected for that identity; a different video can trigger fullscreen once.
- **News** uses the same owned TV Chrome profile and lifecycle for official YouTube Live URLs. Channel Up/Down replaces the owned stream, stopping the prior fullscreen probe before starting the next.
- **Netflix** opens Chrome as a standalone app shell with exactly one `--app=<configured-https-Netflix-URL>`, not a positional URL. The window has no normal Chrome tabs or omnibox, but it is still a Chrome desktop app window—not an Android/native Netflix client. It uses `config/chrome-netflix-profile`, `--start-fullscreen`, `--disable-extensions`, `--autoplay-policy=no-user-gesture-required`, and a debugger bound only to `127.0.0.1`.
- All TV Chrome launches include `--disable-notifications` and `--deny-permission-prompts`; these flags affect only controller-owned TV/Netflix processes and do not write a global Chrome permission policy.
- **Browser** opens the configured browser start URL in its normal browser window.

Netflix navigation canonicalizes nested/duplicate title-card DOM into one logical card per rail position: Left/Right advances exactly one card, while Up/Down chooses the nearest card in the adjacent rail. PWA browse directions intentionally send one command per press instead of hold-repeat. OK clicks one visible card/detail Play or Resume action, waits up to three seconds for a ready watch video, and invokes `video.play()` once if it is still paused before reporting success. BACK prefers Netflix's player back control, PLAY_PAUSE requires a ready video, and FULLSCREEN requests fullscreen with an explicit user gesture. Each operation uses a fresh localhost target lookup and a short CDP WebSocket that closes after the result. Non-idempotent sends, clicks, playback, fullscreen, and submit operations are never replayed when their outcome is unknown.

`NetflixContext` broadcasts only `stage`, `input_kind`, `has_error`, `can_submit`, and an optional browse-only `focused_title` (maximum 120 characters). It never contains a field value, length, email, password, verification code, cookie, token, or session secret. `CommandBus` is the sole state owner: it stores returned Netflix context and clears it on HOME, another app, rollback, or failure. The PWA and Expo clients render inline email/password/code or browse guidance and fall back to their ordinary D-pad/keyboard when context is null or unknown.

HOME never becomes a Netflix DOM command. It minimizes the specific still-owned Netflix app window and restores 我的電視; it never steers or terminates another Chrome process. Chrome and Netflix remain responsible for sign-in, cookies, protected-content authorization, Widevine, and playback. This project does not store credentials, intercept licensing traffic, or bypass DRM. Credentialed browse/direct-play acceptance requires an operator-provided authorized Netflix account and cannot be claimed by automated tests without that external prerequisite. Netflix DOM changes can require a tested runtime update.

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

The script changes only the current user's verified Task Scheduler entry and refuses to overwrite or remove an unrelated same-name task. It does not install a Session-0 Windows service or modify system-wide startup settings. The task may start and continue on battery power, supervises the controller after launch, and uses three one-minute restart attempts rather than an unbounded retry loop.

## Development checkout verification

The following test suites require a full Git checkout; they are intentionally not
included in the release appliance zip. Release users can instead run the
integration smoke test shown below after `scripts\start.ps1 -NoBrowser` succeeds.

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

Integration smoke test for the default HTTP transport (against an active
`start.ps1 -NoBrowser` instance):

```powershell
.\.venv\Scripts\python.exe scripts\integration-smoke.py
```

For HTTPS mode, verify the same instance with its generated controller CA:

```powershell
.\.venv\Scripts\python.exe scripts\integration-smoke.py --transport https --ca-cert config\tls\pc-tv-box-local-ca.cer
```

## Troubleshooting

| Symptom | Action |
|---|---|
| Phone cannot open `/remote` | Same LAN: use the printed numeric IP. Off-LAN: install `cloudflared`, restart `start.ps1`, and rescan the new trycloudflare QR. Do not port-forward 8765. |
| Browser warns about the controller certificate | HTTPS mode only: import `config\tls\pc-tv-box-local-ca.cer` into **Current User → Trusted Root Certification Authorities**. On the phone, transfer and trust the same CA certificate, verifying the fingerprint printed by `start.ps1`. |
| Pairing code rejected | Read the current TV code again; it expires after 10 minutes and becomes invalid after a successful pairing. |
| Brave/Edge unavailable | Confirm the path in `config/settings.json`, then restart the controller. |
| Browser tile reports that a managed window is unavailable | Close existing windows for that browser and retry. The controller waits up to 10 seconds for the exact window created by its child process and refuses to steer an unrelated browser process. |
| Live TV error | Install mpv, set `applications.mpv_path` if needed, and validate your channel URL and authorization. |
| TV Launcher does not foreground on Home | Keep the 我的電視 tab/window open. The launcher title is used to restore its specific browser window. |
| Phone cannot install PWA | A trusted HTTPS controller origin is required for service workers and install prompts. HTTP mode serves Remote as a normal web page. |
| Native Remote cannot connect | Native app is HTTPS-only. Set `server.transport` to `"https"`, install the controller CA as an app CA on Android or enable full trust on iOS, then confirm the numeric IP matches the QR code or `start.ps1` output. Native Remote does not accept PC names. |
| Update says restart required | Close and reopen FreeTV once. The verified staged release is applied before backend dependencies load. If applying it fails, the previous managed files are restored and the pending marker is retained for diagnosis. |

## Security

- Default transport is local HTTP. Off-LAN phones use a Cloudflare HTTPS origin written by `start.ps1`. Pairing code, token auth, Host/Origin checks, 10s auth timeout, and rate limits stay. Do not expose port `8765` on the router.
- In HTTPS mode, state-changing Remote traffic is accepted only through `https://<controller-literal-IP>:<port>` and `wss://<controller-literal-IP>:<port>`, with matching browser Host/Origin; arbitrary hostnames and missing browser Origins are rejected.
- Pairing code display is loopback-only; the unauthenticated TV WebSocket additionally requires the exact local launcher Origin.
- In HTTPS mode the per-user CA signs certificates only for the controller's loopback and current literal IP addresses. Its private key and the token store remain under ignored `config\`.
- Remote sockets must authenticate within 10 seconds. Production launch limits concurrent work, pending pre-authentication sockets, and WebSocket message size.
- Tokens are random, stored only as salted PBKDF2 hashes on PC, and are never logged. Expired, revoked, or evicted Remote sessions are closed and receive no further state.
- A remote can use **Forget** to revoke its persisted token at the controller, immediately closing its paired WebSocket session. Pair it again from the TV code to reconnect.
- Update check/apply accepts only the exact loopback TV origin or a trusted Remote Origin with a valid paired bearer token. Release archives are streamed with size limits, checked against SHA-256, validated against traversal/symlink attacks, and staged before restart.
- Input is validated with versioned Pydantic protocol models at the transport boundary.
- Browser/mpv paths and URLs come only from local typed configuration; subprocess calls use argument arrays, never shell strings.
- The controller binds only to `0.0.0.0` for paired LAN remotes; `scripts/start.ps1` rejects another server host. Do not expose port `8765` to the internet or configure router port forwarding.

## Known limitations

- The Windows installer is a user-scoped, unsigned Inno Setup executable rather than a signed MSI. macOS/Linux still use bootstrap scripts and require Python 3.11+, `curl`, and `unzip`. SHA-256 detects download corruption, while publisher trust remains rooted in the HTTPS GitHub Release account rather than a separately pinned signing key.
- The TV Launcher is a browser window, not a native OS shell replacement. The Windows installer enables current-user logon autostart and opens Chrome/Chromium fullscreen for the appliance flow. Portable installs can run `python freetv.py autostart`. Linux D-pad/volume need xdotool/ydotool and wpctl/pactl.
- HTTP mode cannot install the Remote as a PWA (service workers require a secure context). HTTPS mode requires explicit trust of the controller local CA; the certificate contains literal current IP addresses, so `start.ps1` refreshes it after LAN-address changes.
- Native Remote pairing uses QR or a manually entered numeric IP and remains HTTPS-only. The controller advertises mDNS metadata only in HTTPS mode, but the current native app does not yet provide automatic mDNS discovery.
- Native iOS builds require macOS/Xcode or an authenticated Expo EAS account.
- This project launches existing browsers and mpv only; it does not discover/scrape IPTV streams, bypass DRM, or manage account credentials. Ad blocking is limited strictly to loading the verified store AdBlock extension into the isolated TV Chrome profile.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/PROTOCOL.md](docs/PROTOCOL.md), and [docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md) for implementation details.
