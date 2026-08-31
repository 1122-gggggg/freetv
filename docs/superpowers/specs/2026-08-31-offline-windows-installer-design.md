# Offline Windows Installer Design

## Objective

Make Windows installation a single offline `FreeTV-Setup.exe` under 250 MB. A user downloads it, completes one short wizard, and starts FreeTV without installing Python, opening PowerShell, invoking `winget` or `pip`, or requiring Internet access.

Chrome remains external. A private Python runtime, mpv, cloudflared, the built frontend, backend dependencies, and the primary AdBlock extension ship inside the installer.

## Current problem

The v0.4.1 installer is a 2.2 MB online bootstrap. Its post-install step opens PowerShell, may install Python through winget, creates `.venv`, downloads Python packages and Chrome extensions, and starts the application. A clean install therefore depends on several external services and exposes implementation details to the user.

## Decisions

1. Windows 10/11 x64 is the offline target.
2. Use the official CPython 3.13 x64 embedded distribution. Pin the exact patch version, source URL, architecture, size, and SHA-256 in the repository.
3. Vendor runtime wheels beside the embedded interpreter at release-build time. Do not ship pip or pytest.
4. Bundle baseline x86-64 mpv and x64 cloudflared portable binaries.
5. Bundle only the primary Chrome Web Store AdBlock extension (`gighmmpiobklfepjocnamgkkbiglidom`). Remove the second YouTube-specific extension (`cmedhionkhpnakcndndgjdbohmhepckk`) because its downloaded package and current store listing do not provide verifiable redistribution terms.
6. Keep Chrome external. Missing Chrome is a capability warning, not an installation failure.
7. Replace partial Windows zip updates with complete installer updates.
8. Keep installation per-user and do not modify `PATH` or the system Python.
9. There is no Authenticode certificate. Publish SHA-256 checksums and document the expected SmartScreen unknown-publisher warning.

## Chosen architecture

Use embedded CPython plus portable tools inside the existing Inno Setup installer.

Python documents the embedded distribution specifically for private application runtimes and recommends installing third-party packages alongside it rather than managing them with pip on the target machine. This preserves FreeTV's current Python module layout and diagnostics while removing target-machine setup.

PyInstaller was rejected because the current uvicorn subprocess, dynamic imports, and data directories would need additional freezing-specific work and would be harder to diagnose. Chaining several third-party installers was rejected because it would still modify the system and create multiple update and privilege paths.

## User experience

The README and each Windows Release expose one primary action: download `FreeTV-Setup.exe`.

The wizard contains one concise options page:

- install for the current user — fixed;
- start FreeTV at sign-in — selected by default;
- create a desktop shortcut — selected by default;
- configure appliance power mode — not selected by default.

Only the optional appliance power mode requests administrator approval. Normal installation stays unelevated. Initialization runs hidden, writes to the setup log, and never opens PowerShell or a console. FreeTV starts when installation completes.

No network is required to install, initialize configuration, open the LAN TV interface, pair a LAN remote, or use bundled mpv. A cloudflared tunnel naturally requires network connectivity. Chrome-dependent tiles remain unavailable until Chrome is installed separately.

## Installed layout

```text
%LOCALAPPDATA%\FreeTV\
  freetv.py
  VERSION
  runtime\
    python.exe
    pythonw.exe
    python313.dll
    python313._pth
    site-packages\
  tools\
    mpv\
      mpv.exe
    cloudflared\
      cloudflared.exe
  backend\app\
  frontend\dist\
  vendor\adblock\
  config\
  logs\
  licenses\
  scripts\
```

`config` and `logs` are user state. `runtime`, `tools`, `backend/app`, `frontend/dist`, `vendor/adblock`, managed root files, and third-party notices are release-managed.

## Reproducible release build

A repository-owned lock manifest records each bundled artifact's component, version, architecture, upstream URL, expected size, SHA-256, destination, and license files.

The Windows release job:

1. Builds and tests the frontend and application.
2. Creates an empty offline staging directory.
3. Downloads every locked artifact and rejects a wrong host, redirect, size, architecture, or digest.
4. Extracts CPython under `runtime`.
5. Installs runtime-only Windows wheels under `runtime/site-packages`.
6. Extracts mpv and cloudflared under `tools`.
7. Downloads the primary AdBlock CRX through the existing Chrome Web Store endpoint, validates its CRX3 structure and extension ID, and extracts it under `vendor/adblock`.
8. Copies application code, frontend output, examples, runtime scripts, and third-party notices.
9. Runs the private interpreter directly to prove imports, configuration initialization, bundled executable discovery, and backend startup.
10. Compiles the complete stage with Inno Setup and rejects an installer larger than 250 MB.

The build may use the network. The resulting installer may not. Unpinned `latest` downloads are forbidden in the release job.

## Runtime behavior

`freetv.py` distinguishes execution by interpreter path and installed layout:

- bundled Windows runtime: run application commands directly; never create `.venv` or invoke pip;
- existing project virtual environment: run application commands directly;
- portable/development system Python: preserve the current bootstrap behavior.

Start Menu, desktop, and sign-in launchers call `runtime\pythonw.exe freetv.py start`.

Bundled setup only validates the private runtime and AdBlock files, initializes missing configuration from examples, applies the existing Chrome policy when Chrome is present, and records capability diagnostics. It performs no download.

Application resolution order is:

1. explicit path in `config/settings.json`;
2. existing system candidates and commands;
3. bundled mpv or cloudflared executable.

The second YouTube-specific extension is removed as a clean cutover: no downloader call, vendor directory, launch argument, policy entry, fixture, or documentation reference remains.

## Installation and migration

Inno Setup installs the complete managed bundle before registering autostart or launching FreeTV. Hidden finalization uses `runtime\python.exe`. A failure prevents autostart registration and shows a concise localized message with the log path.

An upgrade preserves `config`, `logs`, launcher choices, and user settings. It completely replaces managed runtime, tool, and vendor trees so removed dependencies cannot linger. Only after the bundled runtime passes finalization does cleanup remove the obsolete installer-created `.venv`.

Updates do not rerun appliance power configuration and do not request UAC.

## Installer-based update flow

Bundled Windows update discovery requires `FreeTV-Setup.exe` and `FreeTV-Setup.exe.sha256` on a newer GitHub Release.

1. The paired user selects update.
2. FreeTV downloads both files to `config/updates`.
3. It validates trusted HTTPS redirects, declared and actual size, and SHA-256.
4. It atomically writes a pending-installer marker and reports that restart is required.
5. On restart, the stdlib-only bootstrap revalidates the marker and digest, launches the installer in silent update mode, and exits before managed files are replaced.
6. The installer replaces the complete bundle, skips appliance-power configuration, finalizes, and restarts FreeTV.
7. Success removes the marker and old installer. Failure retains the marker and setup log for diagnosis.

Portable and non-Windows installations keep the existing zip updater. Update artifact selection uses the active installation mode, not OS inference alone.

## Failure and security boundaries

- Release generation fails for an unverified artifact, missing license, wrong architecture, missing Windows wheel, invalid extension ID, failed private-runtime import, failed startup, or installer over 250 MB.
- No target-machine path invokes a package manager or executes a downloaded script.
- Update URLs remain restricted to HTTPS and trusted GitHub Release hosts; every redirect is checked.
- Installer updates are SHA-256 verified before execution.
- Without Authenticode, checksum validation proves equality with the published release asset, not publisher identity. Documentation states this limitation.
- `config` and `logs` are excluded from managed replacement.

## Verification and completion gate

Automated checks remain focused on changed contracts: bundled-runtime mode, no pip/venv in that mode, explicit/system/bundled executable precedence, installer asset update selection, digest validation, and preservation of user state.

The feature is complete only after these two real user scenarios pass:

### Clean-machine installation

On a clean Windows 10/11 x64 machine with no Python, Node.js, mpv, cloudflared, or project files:

1. Disconnect the machine from the Internet.
2. Double-click the produced `FreeTV-Setup.exe` and use the normal wizard.
3. Confirm no PowerShell window, Python installer, winget, pip, or unexpected UAC appears.
4. Start FreeTV from the installed shortcut.
5. Confirm the backend and frontend become healthy, the TV page opens, a LAN remote can pair, and bundled mpv is usable.
6. Confirm no `.venv` was created and the installed application uses `runtime\pythonw.exe` plus bundled tools.

A successful end-to-end run on this clean machine is the installation acceptance test.

### User-side update

Use two actual GitHub releases:

1. Install the first offline release on the clean machine and create recognizable user configuration.
2. Publish the next patch release with a deliberately small observable update and a new `FreeTV-Setup.exe` plus checksum.
3. Let the installed client detect the release and select update from the user interface.
4. Restart when prompted.
5. Confirm the installer update runs without UAC, FreeTV restarts on the new version, the small change is present, and the prior configuration remains intact.

A successful update initiated by the installed user client is the update acceptance test. No substitute based only on unit tests or unpacking the installer counts as completion.

## Release presentation

Release notes begin with the direct Windows installer link and state: download and double-click; no Python or Internet is required for installation. Checksums, portable zip, command installers, and macOS/Linux assets are grouped as advanced or other-platform downloads.

The README mirrors this order and removes wording that the recommended Windows installer may invoke winget or pip.

## Out of scope

- Bundling Chrome or another Chromium browser.
- Authenticode signing until a certificate or Trusted Signing account exists.
- Offline macOS/Linux installers.
- Replacing cloudflared's online tunnel service.
- Unrelated UI changes.

## Authoritative references

- Python embedded distribution and vendored-package guidance: https://docs.python.org/3/using/windows.html#the-embeddable-package
- mpv Windows builds: https://github.com/shinchiro/mpv-winbuild-cmake/releases
- cloudflared official releases: https://github.com/cloudflare/cloudflared/releases
- Primary AdBlock identity: https://chromewebstore.google.com/detail/adblock/gighmmpiobklfepjocnamgkkbiglidom
- Removed YouTube extension listing: https://chromewebstore.google.com/detail/adblock-for-youtube/cmedhionkhpnakcndndgjdbohmhepckk
