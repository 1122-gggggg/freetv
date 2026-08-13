# Windows 11 Setup

## First installation

1. Install Python 3.11+ and Node.js LTS.
2. Install Brave if YouTube should use Brave.
3. Install [mpv](https://mpv.io/installation/) if Live TV is required. Add its directory to `PATH` or set `applications.mpv_path` in `config/settings.json`.
4. In PowerShell at the repository root, run `Set-ExecutionPolicy -Scope Process Bypass` then `./scripts/setup.ps1`.
5. Review local `config/settings.json` and `config/channels.json`. Those files are intentionally ignored by Git because they are machine-specific.
6. The setup script generates `config\tls\pc-tv-box-local-ca.cer`, a local CA certificate. It does not alter Windows trust stores. Before opening the HTTPS TV page, use Certificate Manager to import that CA into **Current User → Trusted Root Certification Authorities**.

## Network and firewall

The backend binds to `0.0.0.0:8765` so a paired phone can reach `https://<PC-LAN-IP>:8765/remote` on the private LAN. When Windows asks about firewall access, select **Private networks** only. Do not select Public networks and do not add a router port-forwarding rule.

Find the Remote address by running `./scripts/start.ps1`; it prints the selected IPv4 address and CA SHA-256 fingerprint. Open that exact numeric HTTPS address on phones rather than a PC name or custom hostname. Phones must be on the same Wi-Fi/LAN. Guest Wi-Fi often blocks device-to-device traffic and will not work.

Before the first phone connection, transfer `config\tls\pc-tv-box-local-ca.cer` to the phone over a path you trust, compare its fingerprint with the value on the TV/PowerShell output, then install and trust it as a CA certificate. On iOS/iPadOS, enable full trust for the installed root in **Settings → General → About → Certificate Trust Settings**. On Android, install it as a CA certificate for apps; the exact Settings path depends on Android version.

## TV appliance behavior

Run `./scripts/start.ps1` to refresh the IP-address certificate, start the backend, wait for health, and open the local HTTPS TV page. Use the browser's fullscreen mode if desired. The controller uses the MY TV page as the Home destination; keep that page open.

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

YouTube opens Brave using the existing default profile; Google login persists normally. Netflix opens Edge with normal browser DRM. Do not expect automatic Netflix login, credential management, DRM extraction, or ad blocking: none is implemented.

## Live TV behavior

Only add URLs for streams you have a right to use. `channels.json` validates channel IDs, unique channel numbers, and HTTP(S) URLs. mpv controls use its local JSON IPC pipe rather than keyboard automation. If mpv stops, start Live TV again after resolving the error.

## Remote PWA

The Remote has a manifest and service worker. A trusted HTTPS origin is required for browser installation and service-worker support. The production Remote therefore does not accept plaintext LAN HTTP or `ws://` connections; install the local CA before opening it on a phone.
