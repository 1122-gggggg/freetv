# Windows 11 Setup

## Installation methods

### 1. Offline Windows installer (recommended)

Download **FreeTV-Setup.exe** from the latest GitHub Release and double-click it.

- **Self-contained & offline:** Deploys FreeTV under `%LOCALAPPDATA%\FreeTV` with a private Python 3.13 runtime, prebuilt backend, mpv, and cloudflared. No Python, Node.js, winget, pip, or Internet connection is required during installation.
- **Browser requirement:** Google Chrome or Chromium is required for YouTube/News TV playback and Netflix. Internet access is needed when using Chrome and online streaming services, but not for installing FreeTV.
- **SmartScreen warning:** Because releases are not Authenticode-signed, Windows SmartScreen may show an unknown-publisher dialog. Click **More info** → **Run anyway** (verify `FreeTV-Setup.exe.sha256` when authenticity matters).
- **Setup options:**
  - **Desktop shortcut:** Creates a `FreeTV` desktop shortcut.
  - **Logon autostart:** Configures FreeTV to start automatically in background supervised mode when signing in to Windows (via user Startup shortcut).
  - **Lid-close power configuration (optional):** Configures the active Windows power plan so closing a laptop lid does not sleep or hibernate the machine (prompts for UAC only when selected).
- **Updates:** FreeTV checks GitHub Releases for newer `FreeTV-Setup.exe` and `FreeTV-Setup.exe.sha256` assets. Updating via the web/native Remote stages the installer under `config/updates` and executes it silently on restart, updating application binaries while preserving `config`, pairings, and `logs`.

### 2. Portable archive or developer checkout

1. Install Python 3.11+ as `python` on `PATH` or through the Windows `py` launcher. Node.js LTS is needed only if you clone the repo and `frontend\dist` is missing.
2. Install Google Chrome. YouTube/News and Netflix use separate ignored Chrome profiles; Netflix protected playback still depends on Chrome/Widevine and a user-authorized Netflix account.
3. Install [mpv](https://mpv.io/installation/) if Live TV is required. Add its directory to `PATH` or set `applications.mpv_path` in `config/settings.json`.
4. In PowerShell at the repository root or unzipped Release directory (`pc-tv-box.zip`), run `Set-ExecutionPolicy -Scope Process Bypass` then `./scripts/setup.ps1`.
5. Review local `config/settings.json` and `config/channels.json`. Those files are intentionally ignored by Git because they are machine-specific. Default `server.transport` is `"http"`.

Setup validates any existing `.venv` as an isolated Python 3.11+ environment. If it is incomplete, unusable, or too old, setup does not delete it; remove or rename it manually before retrying. Portable updates use `pc-tv-box.zip` and `pc-tv-box.zip.sha256`.

## Network and firewall
The backend binds only to `0.0.0.0:8765` so a paired phone can reach `http://<PC-LAN-IP>:8765/remote` on the private LAN. Keep `server.host` set to `0.0.0.0`; `start.ps1` rejects another binding because the controller's LAN and loopback policies depend on this separation. When Windows asks about firewall access, select **Private networks** only. Do not select Public networks and do not add a router port-forwarding rule.

Find the Remote address by running `./scripts/start.ps1`; it prints the selected IPv4 address. Open that exact numeric address on phones rather than a PC name or custom hostname. Phones must be on the same Wi-Fi/LAN. Guest Wi-Fi often blocks device-to-device traffic and will not work.

## TV appliance behavior

Run `./scripts/start.ps1` to start the backend, wait for health, and open the local TV page. Re-running it restarts only this repository's non-reload production controller when transport or TLS material changed; an unrelated listener on the configured port is rejected. In HTTPS mode startup waits up to 30 seconds for an eligible private LAN address before issuing the controller certificate. If Wi-Fi is still unavailable, startup fails instead of creating a loopback-only certificate; the autostart task then uses its finite retry policy.

When Edge is available, it starts only the local MY TV launcher in Edge's documented full-screen kiosk mode with an absolute dedicated `config\edge-profile`, extensions disabled, and sync disabled. That launcher profile contains no account state and does not share or lock the controller-owned Chrome TV/Netflix profiles or the user's daily Chrome profile. If Edge is unavailable, startup warns and opens the MY TV page in the default browser.

The controller launches only its own browser children. YouTube/News use `config\chrome-tv-profile`; Netflix uses `config\chrome-netflix-profile`. Both profiles receive `--disable-notifications` and `--deny-permission-prompts` on their command line, so setup does not grant a global website permission or alter a daily Chrome profile. HOME and shutdown act only on the tracked PID/HWND tree.

For automatic start after sign-in:
- **Installed Windows app:** The installer automatically creates a user Startup shortcut launching `runtime\pythonw.exe freetv.py start --supervise` without console windows.
- **Portable / developer setup:** Run `./scripts/install-autostart.ps1`. This creates one current-user Task Scheduler task that can start and continue on battery power. Its startup action remains attached as a controller supervisor and makes three one-minute restart attempts after a failure. Remove it with `./scripts/install-autostart.ps1 -Remove`.

## Application paths
Common paths are detected automatically:

- Brave: `C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe`
- Edge: `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`

Set an explicit executable path if your installation differs. Paths are local administrator/user configuration, not Remote input. The controller launches applications with fixed argument arrays.

## Browser behavior

- YouTube and News open controller-owned fullscreen Google Chrome with the TV profile, store AdBlock, localhost-only debugging, and the two permission-prompt suppression flags. A bounded probe requests fullscreen once per new video identity. Escape remains effective for that identity; changing videos permits one new request.
- Netflix opens desktop Chrome with exactly one `--app=<configured HTTPS Netflix URL>` in `config\chrome-netflix-profile`, `--start-fullscreen`, `--disable-extensions`, localhost-only debugging, and the same permission flags. `--app` removes the normal tab strip/omnibox, but this is not an Android/native Netflix app.
- Netflix login, cookie persistence, protected-content permission, Widevine, and playback remain Chrome/Netflix responsibilities. The controller never stores or reads credentials and cannot validate credentialed browse/direct-play without an operator-supplied authorized account.
- The page adapter requires one controller-owned top-level Netflix target. It uses one short CDP socket per operation and never keeps a debugger connection resident. A Netflix site redesign can require an updated tested runtime.
- PWA/Expo Netflix context cards show safe input mode, generic error state, browse title, and navigation hints. Sending clears local password/code text immediately. Null/unknown context falls back to the ordinary D-pad/keyboard.
- The configured Browser tile opens its ordinary browser window independently of the TV and Netflix profiles.

## Live TV behavior

Only add URLs for streams you have a right to use. `channels.json` validates channel IDs, unique channel numbers, and HTTP(S) URLs. mpv controls use its local JSON IPC pipe rather than keyboard automation. If mpv stops, start Live TV again after resolving the error.

## Remote PWA

The Remote has a manifest and service worker. A trusted HTTPS origin is required for browser installation and service-worker support. Default HTTP mode therefore serves Remote as a normal web page; "install as app" is unavailable. To restore encrypted Remote and PWA install, see **HTTPS mode (optional)** below.

## HTTPS mode (optional)

Set `"server": { "host": "0.0.0.0", "port": 8765, "transport": "https" }` in `config/settings.json`, then re-run `./scripts/setup.ps1` and `./scripts/start.ps1`. Setup generates `config\tls\pc-tv-box-local-ca.cer`. It does not alter Windows trust stores. Before opening the HTTPS TV page, use Certificate Manager to import that CA into **Current User → Trusted Root Certification Authorities**.

Before the first phone connection, transfer `config\tls\pc-tv-box-local-ca.cer` to the phone over a path you trust, compare its fingerprint with the value on the TV/PowerShell output, then install and trust it as a CA certificate. On iOS/iPadOS, enable full trust for the installed root in **Settings → General → About → Certificate Trust Settings**. On Android, install it as a CA certificate for apps; the exact Settings path depends on Android version. Native Remote remains HTTPS-only.
