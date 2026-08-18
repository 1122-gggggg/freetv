# Windows 11 Setup

## First installation

1. Install Python 3.11+. Node.js LTS is needed only if you clone the repo and `frontend\dist` is missing.
2. Install Brave if YouTube should use Brave.
3. Install [mpv](https://mpv.io/installation/) if Live TV is required. Add its directory to `PATH` or set `applications.mpv_path` in `config/settings.json`.
4. In PowerShell at the repository root or unzipped Release directory, run `Set-ExecutionPolicy -Scope Process Bypass` then `./scripts/setup.ps1`.
5. Review local `config/settings.json` and `config/channels.json`. Those files are intentionally ignored by Git because they are machine-specific. Default `server.transport` is `"http"`.

## Network and firewall

The backend binds only to `0.0.0.0:8765` so a paired phone can reach `http://<PC-LAN-IP>:8765/remote` on the private LAN. Keep `server.host` set to `0.0.0.0`; `start.ps1` rejects another binding because the controller's LAN and loopback policies depend on this separation. When Windows asks about firewall access, select **Private networks** only. Do not select Public networks and do not add a router port-forwarding rule.

Find the Remote address by running `./scripts/start.ps1`; it prints the selected IPv4 address. Open that exact numeric address on phones rather than a PC name or custom hostname. Phones must be on the same Wi-Fi/LAN. Guest Wi-Fi often blocks device-to-device traffic and will not work.

## TV appliance behavior

Run `./scripts/start.ps1` to start the backend, wait for health, and open the local TV page. When Edge is available, it starts the launcher in Edge's documented full-screen kiosk mode with an absolute dedicated profile directory (`--user-data-dir` under `config\edge-profile`), extensions disabled, and sync disabled. The launcher itself has no account state, and this dedicated user data directory ensures the TV kiosk runs in a separate process that does not share, lock, or affect YouTube or Netflix's normal browser profiles. If Edge is unavailable, the script warns and falls back to the default browser without profile overrides. The controller uses the MY TV page as the Home destination; keep that page open.

For automatic start after sign-in:

```powershell
./scripts/install-autostart.ps1
```

This creates one current-user Task Scheduler task. It is not a Windows service and does not run in Session 0. Remove it with `./scripts/install-autostart.ps1 -Remove`.

## Application paths

Common paths are detected automatically:

- Brave: `C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe`
- Edge: `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`

Set an explicit executable path if your installation differs. Paths are local administrator/user configuration, not Remote input. The controller launches applications with fixed argument arrays.

## Browser behavior

YouTube opens Brave using the existing default profile; Google login persists normally. Netflix opens Edge with normal browser DRM and user profile state, completely isolated from the TV kiosk session. Do not expect automatic Netflix login, credential management, DRM extraction, or ad blocking: none is implemented.

## Live TV behavior

Only add URLs for streams you have a right to use. `channels.json` validates channel IDs, unique channel numbers, and HTTP(S) URLs. mpv controls use its local JSON IPC pipe rather than keyboard automation. If mpv stops, start Live TV again after resolving the error.

## Remote PWA

The Remote has a manifest and service worker. A trusted HTTPS origin is required for browser installation and service-worker support. Default HTTP mode therefore serves Remote as a normal web page; "install as app" is unavailable. To restore encrypted Remote and PWA install, see **HTTPS mode (optional)** below.

## HTTPS mode (optional)

Set `"server": { "host": "0.0.0.0", "port": 8765, "transport": "https" }` in `config/settings.json`, then re-run `./scripts/setup.ps1` and `./scripts/start.ps1`. Setup generates `config\tls\pc-tv-box-local-ca.cer`. It does not alter Windows trust stores. Before opening the HTTPS TV page, use Certificate Manager to import that CA into **Current User → Trusted Root Certification Authorities**.

Before the first phone connection, transfer `config\tls\pc-tv-box-local-ca.cer` to the phone over a path you trust, compare its fingerprint with the value on the TV/PowerShell output, then install and trust it as a CA certificate. On iOS/iPadOS, enable full trust for the installed root in **Settings → General → About → Certificate Trust Settings**. On Android, install it as a CA certificate for apps; the exact Settings path depends on Android version. Native Remote remains HTTPS-only.
