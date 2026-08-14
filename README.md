# PC TV Box

A local Windows 11 controller that turns an HDMI-connected PC into a TV-style launcher. It serves a 10-foot TV interface at `/tv` and a paired phone remote at `/remote`; no cloud service, IPTV discovery, DRM bypass, ad blocking, or arbitrary remote shell/keyboard API is included.

## Requirements

- Windows 11, signed in as the user who will run the TV controller.
- Python 3.11+ and Node.js LTS.
- Microsoft Edge for Netflix. Windows 11 normally installs it.
- Brave for YouTube. Existing Brave profiles are reused.
- [mpv](https://mpv.io/installation/) for Live TV.
- Laptop/PC and phone on the same private LAN/Wi-Fi.
- The controller's local CA must be trusted on the TV Windows user and on every phone that will use the encrypted Remote.
- Native Android builds additionally require Android Studio, its Android SDK, and a JDK. Native iOS builds require macOS/Xcode or an authenticated Expo EAS build account.

## Installation

Open PowerShell in the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

The setup script creates `.venv`, installs Python and Node dependencies, builds the frontend, creates ignored `config/settings.json` and `config/channels.json` from their examples, and creates a controller-specific local CA plus an IP-address TLS certificate in ignored `config\tls`. It does not alter Windows trust stores. Before opening the HTTPS TV page, import `config\tls\pc-tv-box-local-ca.cer` into **Current User → Trusted Root Certification Authorities** using Certificate Manager.

Configure nonstandard executable locations in `config/settings.json`:

```json
{
  "applications": {
    "brave_path": "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
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

The script builds the frontend if necessary, creates/refreshes the local TLS certificate for current LAN IPs, starts the controller on port `8765`, waits for `/api/health`, then opens the local TV Launcher in Edge full-screen kiosk mode when Edge is available. It falls back to the default browser with a warning otherwise. On the first Windows Firewall prompt, allow the controller only on **Private** networks; do not create port-forwarding rules.

- TV Launcher: `https://127.0.0.1:8765/tv`
- Phone Remote: `https://<PC-LAN-IP>:8765/remote`
- Health: `https://127.0.0.1:8765/api/health`

Use the exact numeric LAN address printed by the script. The controller intentionally rejects device names and arbitrary hostnames for Remote traffic. Before the first phone visit, transfer `config\tls\pc-tv-box-local-ca.cer` through a channel you trust, compare its SHA-256 fingerprint with the value printed by `start.ps1`, and install/trust it on the phone. On iPhone/iPad, enable full trust for the installed root certificate in Certificate Trust Settings. Android certificate-install wording varies by version; install it as a CA certificate for apps, then open the numeric HTTPS URL.

For frontend/backend development:

```powershell
.\scripts\dev.ps1
```

It runs Vite on `http://127.0.0.1:5173` and proxies `/api` and `/ws` to the local backend.

## Pair a phone

1. Install and trust the controller local CA on the phone before opening the HTTPS Remote URL.
2. Open the TV Launcher on the HDMI display.
3. Read the six-digit **Pair Remote** code shown at the lower left.
4. On the phone, open the numeric LAN HTTPS Remote URL printed by `start.ps1`; do not replace it with a PC name or custom hostname.
5. The PWA stores the opaque token in its local storage. The native app stores it in the OS secure store.
6. The Remote reconnects automatically after temporary Wi-Fi or server interruptions.

Pairing codes expire after 10 minutes and can be used once. Five failed attempts from one LAN address pause further attempts for one minute. Use **Forget** on the Remote to remove its local token.

## Native Remote app

`mobile/` is an Expo/React Native app for Android and iOS. It scans the TV pairing QR code, supports manual numeric-IP pairing, stores Remote tokens in device-bound secure storage, and exposes the same typed Remote controls, touchpad, text input, reconnect, and token-revocation flow as the PWA.

Before pairing, install and trust the controller CA as described above. Android builds include a network-security configuration that trusts user-installed CAs for this app; iOS still requires enabling full trust for the imported CA. The app deliberately does not scan arbitrary LAN addresses: use the TV QR code or enter the numeric LAN IP printed by `start.ps1`.

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
- Home: minimize/stop the project-owned active application and return to MY TV.
- Space: Play/Pause.

The phone Remote exposes the same typed command set plus text input and a constrained touchpad:

- One-finger drag: bounded relative mouse motion.
- One tap / double tap: left click / double click.
- Two-finger vertical drag: mouse-wheel scrolling.
- Text: up to 256 sanitized printable characters, sent as Unicode input to the active application.

The Remote never offers raw key sequences, shell commands, PowerShell commands, file paths, or unrestricted pointer coordinates.

## YouTube, Netflix, and Browser

- **YouTube** opens Brave in a new maximized window at the configured YouTube URL. It keeps your normal Brave profile and login state.
- **Netflix** opens Edge in a new maximized window at Netflix. Login and DRM remain entirely inside Edge/Widevine; this project does not bypass or automate DRM or credentials.
- **Browser** opens the configured browser start URL. By default it uses Edge when no `browser_path` is specified.

Only a concrete window/process launched by this controller is minimized or terminated. The controller never kills every Brave, Edge, or mpv process on the machine.

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
| Phone cannot open `/remote` | Confirm both devices use the same LAN, use the exact numeric HTTPS IP printed by `start.ps1`, install the controller local CA on the phone, and allow the app through Windows Firewall on Private networks only. |
| Browser warns about the controller certificate | Import `config\tls\pc-tv-box-local-ca.cer` into **Current User → Trusted Root Certification Authorities**. On the phone, transfer and trust the same CA certificate, verifying the fingerprint printed by `start.ps1`. |
| Pairing code rejected | Read the current TV code again; it expires after 10 minutes and becomes invalid after a successful pairing. |
| Brave/Edge unavailable | Confirm the path in `config/settings.json`, then restart the controller. |
| Live TV error | Install mpv, set `applications.mpv_path` if needed, and validate your channel URL and authorization. |
| TV Launcher does not foreground on Home | Keep the MY TV tab/window open. The launcher title is used to restore its specific browser window. |
| Phone cannot install PWA | A trusted HTTPS controller origin is required for service workers and install prompts. Confirm the local CA is trusted on the phone. |
| Native Remote cannot connect | Install the controller CA as an app CA on Android or enable full trust on iOS, then confirm the numeric IP matches the QR code or `start.ps1` output. Native Remote does not accept PC names. |

## Security

- State-changing Remote traffic is accepted only through `https://<controller-literal-IP>:<port>` and `wss://<controller-literal-IP>:<port>`, with matching browser Host/Origin; arbitrary hostnames and missing browser Origins are rejected.
- Pairing code display is loopback-only; the unauthenticated TV WebSocket additionally requires the exact local launcher Origin.
- The per-user CA signs certificates only for the controller's loopback and current literal IP addresses. Its private key and the token store remain under ignored `config\`.
- Remote sockets must authenticate within 10 seconds. Production launch limits concurrent work, pending pre-authentication sockets, and WebSocket message size.
- Tokens are random, stored only as salted PBKDF2 hashes on PC, and are never logged. Expired, revoked, or evicted Remote sessions are closed and receive no further state.
- A remote can use **Forget** to revoke its persisted token at the controller, immediately closing its paired WebSocket session. Pair it again from the TV code to reconnect.
- Input is validated with versioned Pydantic protocol models at the transport boundary.
- Browser/mpv paths and URLs come only from local typed configuration; subprocess calls use argument arrays, never shell strings.
- The controller binds only to `0.0.0.0` for paired LAN remotes; `scripts/start.ps1` rejects another server host. Do not expose port `8765` to the internet or configure router port forwarding.

## Known limitations

- The TV Launcher is a browser window, not a native Windows shell replacement. Configure Windows sign-in/autostart and use fullscreen/maximized browser behavior for the closest appliance flow.
- PWA and native Remote clients require explicit trust of the controller local CA. The certificate contains literal current IP addresses, so `start.ps1` refreshes it after LAN-address changes.
- Native Remote pairing uses QR or a manually entered numeric IP; mDNS discovery is not implemented in this release.
- Native iOS builds require macOS/Xcode or an authenticated Expo EAS account.
- This project launches existing browsers and mpv only; it does not discover streams, bypass DRM, block ads, or manage account credentials.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/PROTOCOL.md](docs/PROTOCOL.md), and [docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md) for implementation details.
