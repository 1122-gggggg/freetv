# Offline Windows Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Windows 10/11 x64 `FreeTV-Setup.exe` under 250 MB that installs and starts FreeTV without target-machine Python, Node.js, winget, pip, PowerShell windows, or Internet access, then prove a real user can update it through FreeTV.

**Architecture:** Build a release-managed application tree containing CPython 3.13.15's embedded runtime, Windows wheels, portable mpv, and portable cloudflared, then compress it with the existing Inno Setup installer. The bootstrap detects the private runtime and bypasses `.venv`/pip. Bundled Windows clients update by downloading, hashing, and launching the next complete installer; portable clients retain zip updates.

**Tech Stack:** Python 3.13.15 embedded distribution, FastAPI/uvicorn, PowerShell 5.1+, Inno Setup 6, GitHub Actions, portable mpv, cloudflared, pytest, Pester.

## Global Constraints

- Windows target: Windows 10/11 x64; Inno `MinVersion=10.0.17763` and `x64compatible` remain.
- Installer size: at most `250 * 1024 * 1024` bytes.
- Normal installation is per-user and unelevated; only the optional appliance-power task may request UAC.
- Installation and finalization perform no network request and do not invoke winget, pip, npm, or a system Python.
- Chrome remains external. Keep only Web Store policy ID `gighmmpiobklfepjocnamgkkbiglidom`; do not download or redistribute CRX files.
- Bundle baseline x86-64 mpv and x64 cloudflared; explicit config and system installs take precedence over bundled tools.
- Preserve `config`, `logs`, launcher selections, and user settings during update.
- Bundled Windows updates use `FreeTV-Setup.exe` plus `FreeTV-Setup.exe.sha256`; portable installations retain `pc-tv-box.zip` updates.
- No Authenticode claim. Publish and verify SHA-256, and document SmartScreen's unknown-publisher warning.
- Final completion requires the two real-machine scenarios in Tasks 8 and 9; automated tests alone do not count.

## File Structure

**Create**

- `backend/requirements-dev.txt` — test-only requirements layered over runtime requirements.
- `backend/requirements-windows.lock.txt` — exact Python 3.13 Windows x64 wheels and hashes.
- `installer/windows-bundle.lock.json` — exact source, size, hash, architecture, and license metadata for bundled artifacts.
- `installer/licenses/mpv-LICENSE.GPL` — mpv GPL-2.0-or-later license from mpv v0.41.0.
- `installer/licenses/cloudflared-LICENSE` — cloudflared Apache-2.0 license from tag `2026.8.2`.
- `scripts/tests/installer.Tests.ps1` — installed-state assertions against the real Inno output.
- `scripts/build-offline-bundle.ps1` — deterministic assembly of the installer source tree.

**Modify**

- `freetv.py` — recognize the private runtime and hand off pending installer updates before loading dependencies.
- `backend/app/installer.py` — stdlib-only private-runtime detection and pending-installer validation/launch.
- `backend/app/appliance.py` — use the private runtime, skip pip in bundled mode, resolve bundled cloudflared, and avoid extension downloads.
- `backend/app/config.py` — add cloudflared configuration and system/bundled resolution.
- `backend/app/applications/chrome_policy.py` — retain only the primary AdBlock Store policy.
- `backend/app/applications/manager.py` — remove unused local-extension constructor arguments and fields.
- `backend/app/system/updater.py` — select installer assets in bundled mode and stream verified installers to disk.
- `config/settings.example.json` — expose `cloudflared_path`.
- `scripts/setup.ps1` — stop downloading CRX files; keep Store policy application.
- `scripts/build-installer.ps1` — compile from an offline bundle stage rather than the portable zip directly.
- `installer/FreeTV.iss` — private-runtime shortcuts, concise tasks, hidden finalization, update mode, and legacy cleanup.
- `.github/workflows/ci.yml` — install development requirements for tests.
- `.github/workflows/release.yml` — assemble, size-check, offline-smoke, and publish the complete installer.
- `README.md` and `docs/WINDOWS_SETUP.md` — one primary Windows download path and exact offline/update behavior.
- `backend/tests/test_installer.py`, `test_appliance.py`, `test_config.py`, `test_applications.py`, `test_chrome_policy.py`, and `test_updater.py` — changed-contract coverage.
- `VERSION` — release versions `0.5.0`, then `0.5.1` for the user update proof.

**Delete**

- `backend/app/applications/adblock.py` — obsolete CRX downloader/unpacker.
- `backend/tests/test_adblock.py` — tests for the removed downloader.

---

### Task 1: Private Runtime Bootstrap

**Files:**
- Modify: `backend/app/installer.py:1-199`
- Modify: `freetv.py:17-126`
- Modify: `backend/app/appliance.py:17-182,185-326,387-464`
- Modify: `backend/tests/test_installer.py:1-230`
- Modify: `backend/tests/test_appliance.py:1-60`

**Interfaces:**
- Produces: `bundled_runtime_python(root: Path, *, windowed: bool = False, os_name: str = os.name) -> Path`
- Produces: `is_bundled_runtime(root: Path, *, executable: Path | None = None, os_name: str = os.name) -> bool`
- Produces: `application_python(root: Path | None = None, *, os_name: str = os.name) -> Path`
- Preserves: `venv_python(...)` for portable/development installs.

- [ ] **Step 1: Add failing bundled-runtime tests**

Add assertions equivalent to:

```python
from app.installer import bundled_runtime_python, is_bundled_runtime


def test_bundled_runtime_paths_are_private_to_install_root(tmp_path: Path) -> None:
    assert bundled_runtime_python(tmp_path, os_name="nt") == tmp_path / "runtime" / "python.exe"
    assert bundled_runtime_python(tmp_path, windowed=True, os_name="nt") == (
        tmp_path / "runtime" / "pythonw.exe"
    )


def test_bundled_runtime_detection_accepts_python_and_pythonw(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for name in ("python.exe", "pythonw.exe"):
        executable = runtime / name
        executable.touch()
        assert is_bundled_runtime(tmp_path, executable=executable, os_name="nt")


def test_application_python_prefers_bundled_runtime(tmp_path: Path) -> None:
    bundled = tmp_path / "runtime" / "python.exe"
    bundled.parent.mkdir()
    bundled.touch()
    assert application_python(tmp_path, os_name="nt") == bundled
```

In `test_installer.py`, add a bootstrap test that monkeypatches `freetv.is_bundled_runtime` to `True`, replaces `freetv._run_application` with a recorder, makes `freetv._run` raise if called, invokes `freetv.main(["setup"])`, and asserts no venv/pip command ran.

- [ ] **Step 2: Run the focused tests and confirm the missing interfaces fail**

Run:

```powershell
python -m pytest backend/tests/test_installer.py backend/tests/test_appliance.py -q
```

Expected: collection or assertion failures for the three new runtime interfaces.

- [ ] **Step 3: Implement stdlib-only runtime detection**

Add to `backend/app/installer.py`:

```python
def bundled_runtime_python(
    root: Path, *, windowed: bool = False, os_name: str = os.name
) -> Path:
    name = "pythonw.exe" if windowed else "python.exe"
    return root / "runtime" / name if os_name == "nt" else root / "runtime" / "bin" / "python"


def is_bundled_runtime(
    root: Path,
    *,
    executable: Path | None = None,
    os_name: str = os.name,
) -> bool:
    if os_name != "nt":
        return False
    current = (executable or Path(sys.executable)).resolve()
    return current in {
        bundled_runtime_python(root, os_name=os_name).resolve(),
        bundled_runtime_python(root, windowed=True, os_name=os_name).resolve(),
    }
```

Import `sys` without introducing any third-party import. Re-export both functions from `freetv.py`'s existing `_INSTALLER` module load.

Extract the dependency-loading tail of `freetv.main` into:

```python
def _run_application(raw_arguments: list[str]) -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from app.appliance import main as appliance_main
    except ImportError:
        sys.stderr.write("FreeTV 執行環境不完整。請重新安裝 FreeTV。\n")
        return 1
    return appliance_main(raw_arguments)
```

Call `_run_application` immediately when `is_bundled_runtime(ROOT)` is true, before the `.venv` bootstrap branch. Preserve portable behavior unchanged.

In `appliance.py`, implement `application_python` by returning an existing bundled interpreter first and otherwise `venv_python`. `setup_appliance` must skip venv creation and both pip commands only when `is_bundled_runtime(base)` is true; `start_appliance`, `print_doctor`, and non-Windows autostart use `application_python` where they mean the active application runtime.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m pytest backend/tests/test_installer.py backend/tests/test_appliance.py -q
```

Expected: all tests pass; existing portable setup tests still assert pip use outside bundled mode.

- [ ] **Step 5: Commit the bootstrap slice**

```powershell
git add freetv.py backend/app/installer.py backend/app/appliance.py backend/tests/test_installer.py backend/tests/test_appliance.py
git commit -m "feat: support private Windows runtime"
```

### Task 2: Bundled Tool Resolution and Extension Cleanup

**Files:**
- Modify: `backend/app/config.py:21-28,168-222`
- Modify: `backend/app/appliance.py:138-199,220-358`
- Modify: `backend/app/applications/chrome_policy.py:1-65`
- Modify: `backend/app/applications/manager.py:109-149`
- Modify: `scripts/setup.ps1:178-194`
- Modify: `config/settings.example.json`
- Modify: `backend/tests/test_config.py:90-140`
- Modify: `backend/tests/test_applications.py:250-290`
- Modify: `backend/tests/test_chrome_policy.py:1-40`
- Delete: `backend/app/applications/adblock.py`
- Delete: `backend/tests/test_adblock.py`

**Interfaces:**
- Extends: `ApplicationSettings.cloudflared_path: str = ""`
- Extends: `resolve_application_paths(..., root: Path | None = None) -> dict[str, Path | None]` with key `cloudflared`.
- Produces: `cloudflare_network_available(*, timeout_seconds: float = 0.75) -> bool`.
- Removes: `ApplicationManager(..., adblock_dir=..., adblock_youtube_dir=...)`.
- Removes: `ADBLOCK_YOUTUBE_EXTENSION_ID` and all CRX download/unpack APIs.

- [ ] **Step 1: Write path-precedence and single-policy tests**

Add tests with temporary executables and monkeypatched search roots:

```python
def test_resolve_application_paths_prefers_system_mpv_over_bundle(tmp_path, monkeypatch) -> None:
    bundled = tmp_path / "tools" / "mpv" / "mpv.exe"
    bundled.parent.mkdir(parents=True)
    bundled.touch()
    system = tmp_path / "system" / "mpv.exe"
    system.parent.mkdir()
    system.touch()
    monkeypatch.setattr(config.shutil, "which", lambda name: str(system) if name == "mpv.exe" else None)

    paths = resolve_application_paths(Settings(), os_name="nt", root=tmp_path)

    assert paths["mpv"] == system


def test_resolve_application_paths_falls_back_to_bundled_tools(tmp_path, monkeypatch) -> None:
    mpv = tmp_path / "tools" / "mpv" / "mpv.exe"
    cloudflared = tmp_path / "tools" / "cloudflared" / "cloudflared.exe"
    for executable in (mpv, cloudflared):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch()
    monkeypatch.setattr(config.shutil, "which", lambda _: None)

    paths = resolve_application_paths(Settings(), os_name="nt", root=tmp_path)

    assert paths["mpv"] == mpv
    assert paths["cloudflared"] == cloudflared

def test_cloudflare_network_probe_fails_fast_offline(monkeypatch) -> None:
    def offline(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(appliance.socket, "create_connection", offline)
    assert not appliance.cloudflare_network_available(timeout_seconds=0.01)
```

Change Chrome policy tests to expect exactly one entry whose value starts with the primary ID and ends with `STORE_UPDATE_URL`. Change application-manager construction tests so passing removed extension-directory keywords fails until fixtures are migrated.

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
python -m pytest backend/tests/test_config.py backend/tests/test_chrome_policy.py backend/tests/test_applications.py backend/tests/test_appliance.py -q
```

Expected: failures for missing `root`, missing `cloudflared`, the absent network probe, and the still-present second policy.

- [ ] **Step 3: Implement one resolver and remove dead extension code**

Add `cloudflared_path` to the Pydantic model and JSON example. Make bundled candidates the final entries:

```python
base = root or project_root()
bundled_mpv = base / "tools" / "mpv" / "mpv.exe"
bundled_cloudflared = base / "tools" / "cloudflared" / "cloudflared.exe"
```

Resolve configured path, OS candidates/`shutil.which`, then bundled path. Return `cloudflared` in the same dictionary. Pass `root=base` in appliance calls. Replace both direct `shutil.which("cloudflared")` calls with `paths["cloudflared"]`. Before starting a tunnel, call `cloudflare_network_available`, implemented as a `socket.create_connection(("1.1.1.1", 443), timeout=timeout_seconds)` context manager that catches `OSError`; skip the tunnel immediately when offline so bundling cloudflared cannot add a 30-second offline startup delay.

Move `ADBLOCK_EXTENSION_ID` into `chrome_policy.py`, set:

```python
FORCE_INSTALL_EXTENSIONS = ((ADBLOCK_EXTENSION_ID, STORE_UPDATE_URL),)
```

Delete the CRX module and its tests. Remove both dead local-extension parameters/fields from `ApplicationManager` and its test helpers. In `setup_appliance` and `scripts/setup.ps1`, remove the `app.applications.adblock` invocation and retain only Chrome policy application.

- [ ] **Step 4: Run affected backend tests**

```powershell
python -m pytest backend/tests/test_config.py backend/tests/test_chrome_policy.py backend/tests/test_applications.py backend/tests/test_appliance.py -q
```

Expected: all pass; no import or reference to `ADBLOCK_YOUTUBE_EXTENSION_ID`, `ensure_tv_adblockers`, or `adblock_youtube_dir` remains.

- [ ] **Step 5: Commit the tool and policy slice**

```powershell
git add backend/app backend/tests scripts/setup.ps1 config/settings.example.json
git commit -m "feat: use bundled media tools"
```

### Task 3: Deterministic Offline Bundle Builder

**Files:**
- Create: `backend/requirements-dev.txt`
- Create: `backend/requirements-windows.lock.txt`
- Create: `installer/windows-bundle.lock.json`
- Create: `installer/licenses/mpv-LICENSE.GPL`
- Create: `installer/licenses/cloudflared-LICENSE`
- Create: `scripts/build-offline-bundle.ps1`
- Modify: `backend/requirements.txt:1-10`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml:69-79,95-145`

**Interfaces:**
- Produces CLI: `build-offline-bundle.ps1 -PackagePath <zip> -OutputPath <dir> [-BuildPythonPath <exe>] [-SevenZipPath <exe>]`.
- Produces stage paths `runtime/python.exe`, `runtime/pythonw.exe`, `runtime/site-packages`, `tools/mpv/mpv.exe`, `tools/cloudflared/cloudflared.exe`, and `licenses/*`.

- [ ] **Step 1: Split and lock runtime dependencies**

Remove `pytest>=8.3` from `backend/requirements.txt`. Create:

```text
-r requirements.txt
pytest>=8.3
```

Generate and commit the exact Python 3.13 Windows x64 wheel lock:

```powershell
uv pip compile backend/requirements.txt `
  --python-version 3.13 `
  --python-platform x86_64-pc-windows-msvc `
  --only-binary :all: `
  --generate-hashes `
  --output-file backend/requirements-windows.lock.txt
```

Update CI test jobs to install `backend/requirements-dev.txt`; the bundle builder installs `backend/requirements-windows.lock.txt` with hash enforcement.

- [ ] **Step 2: Add the exact lock manifest**

Create `installer/windows-bundle.lock.json` with these immutable values:

```json
{
  "schema_version": 1,
  "python": {
    "version": "3.13.15",
    "architecture": "x86_64",
    "url": "https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip",
    "size": 11009825,
    "sha256": "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"
  },
  "mpv": {
    "version": "20260831-git-e8673660ab",
    "architecture": "x86_64",
    "url": "https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20260831/mpv-x86_64-20260831-git-e8673660ab.7z",
    "size": 33769581,
    "sha256": "9021f3db28c994981d8cb58b0991683a89a5240967ef2aa0f34503a203fdc8dc"
  },
  "cloudflared": {
    "version": "2026.8.2",
    "architecture": "x86_64",
    "url": "https://github.com/cloudflare/cloudflared/releases/download/2026.8.2/cloudflared-windows-amd64.exe",
    "size": 54893480,
    "sha256": "c29eee2b121f5436a642eed69fd9767da7e7b8c510fa50aaa130337f931357b5"
  }
}
```

Copy the exact upstream license texts from `mpv-player/mpv` tag `v0.41.0` and `cloudflare/cloudflared` tag `2026.8.2`; preserve their filenames and full text.

- [ ] **Step 3: Implement verified staging**

The script must use strict mode, parse the lock, and verify both size and digest before extraction:

```powershell
function Get-VerifiedArtifact {
    param([object]$Component, [string]$Destination)
    Invoke-WebRequest -UseBasicParsing -Uri $Component.url -OutFile $Destination
    $item = Get-Item -LiteralPath $Destination
    if ($item.Length -ne [int64]$Component.size) {
        throw "Artifact size mismatch for $($Component.url)."
    }
    $actual = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne [string]$Component.sha256) {
        throw "Artifact SHA-256 mismatch for $($Component.url)."
    }
}
```

Reject URLs outside `www.python.org`, `github.com`, and GitHub release-asset redirect hosts. Expand the portable package first, Python with `Expand-Archive`, mpv with the resolved 7-Zip executable, and copy cloudflared directly.

Vendor wheels with the build interpreter:

```powershell
& $BuildPythonPath -m pip install `
    --disable-pip-version-check `
    --only-binary=:all: `
    --require-hashes `
    --target (Join-Path $OutputPath 'runtime\site-packages') `
    -r (Join-Path $Root 'backend\requirements-windows.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Vendoring locked Windows runtime wheels failed.' }
```

Write `runtime/python313._pth` as ASCII:

```text
python313.zip
.
site-packages
..\backend
```

Copy Python's embedded `LICENSE.txt`, the two committed licenses, and a generated component/version/source table under `licenses`.

- [ ] **Step 4: Build and execute the staged runtime**

Install 7-Zip as a build prerequisite if not present, then run:

```powershell
./scripts/package.ps1 -OutputPath $env:TEMP\pc-tv-box.zip
./scripts/build-offline-bundle.ps1 `
  -PackagePath $env:TEMP\pc-tv-box.zip `
  -OutputPath $env:TEMP\freetv-offline-stage
& $env:TEMP\freetv-offline-stage\runtime\python.exe -c `
  "import fastapi, uvicorn, websockets, pydantic, psutil, cryptography, pycaw, httpx, zeroconf; print('runtime-ok')"
```

Expected: `runtime-ok`; `runtime\python.exe` and both tool executables exist; `runtime\Scripts\pip.exe`, `.venv`, and `vendor\adblock` do not exist.

- [ ] **Step 5: Commit the bundle builder**

```powershell
git add backend/requirements.txt backend/requirements-dev.txt backend/requirements-windows.lock.txt installer scripts/build-offline-bundle.ps1 .github/workflows/ci.yml .github/workflows/release.yml
git commit -m "build: assemble offline Windows bundle"
```

### Task 4: Offline Inno Installer

**Files:**
- Modify: `scripts/build-installer.ps1:1-84`
- Modify: `installer/FreeTV.iss:15-110`
- Create: `scripts/tests/installer.Tests.ps1`

**Interfaces:**
- `build-installer.ps1` compiles only from a verified offline stage.
- Inno custom parameter `/UPDATE=1` identifies a silent application update.
- Inno tasks: `autostart`, `desktopicon`, and `appliancepower`.

- [ ] **Step 1: Add installed-state Pester assertions**

Create `scripts/tests/installer.Tests.ps1` with a required install root and behavior checks:

```powershell
param([Parameter(Mandatory = $true)][string]$InstallRoot)

Describe 'Offline FreeTV installation' {
    It 'uses the bundled runtime without a virtual environment' {
        Test-Path (Join-Path $InstallRoot 'runtime\python.exe') | Should -BeTrue
        Test-Path (Join-Path $InstallRoot 'runtime\pythonw.exe') | Should -BeTrue
        Test-Path (Join-Path $InstallRoot '.venv') | Should -BeFalse
    }

    It 'contains both bundled tools' {
        Test-Path (Join-Path $InstallRoot 'tools\mpv\mpv.exe') | Should -BeTrue
        Test-Path (Join-Path $InstallRoot 'tools\cloudflared\cloudflared.exe') | Should -BeTrue
    }

    It 'has a healthy private runtime' {
        & (Join-Path $InstallRoot 'runtime\python.exe') -c `
            'import fastapi, uvicorn, cryptography, pycaw, zeroconf'
        $LASTEXITCODE | Should -Be 0
    }
}
```

- [ ] **Step 2: Run against the existing v0.4.1 installation and verify failure**

```powershell
$container = New-PesterContainer `
  -Path ./scripts/tests/installer.Tests.ps1 `
  -Data @{ InstallRoot = (Join-Path $env:LOCALAPPDATA 'FreeTV') }
Invoke-Pester -Container $container
```

Expected: failure because v0.4.1 uses `.venv` and has no `runtime` or bundled tools.

- [ ] **Step 3: Compile from the offline stage**

Change `build-installer.ps1` so its temporary work sequence is:

```powershell
$BundleRoot = Join-Path $StageRoot 'offline-bundle'
& (Join-Path $PSScriptRoot 'build-offline-bundle.ps1') `
    -PackagePath $PackagePath `
    -OutputPath $BundleRoot
if ($LASTEXITCODE -ne 0) { throw 'Offline bundle assembly failed.' }
$SourceRoot = $BundleRoot
```

Remove the direct package extraction path. Keep semantic-version validation and Inno output verification.

- [ ] **Step 4: Replace online post-install behavior**

In `FreeTV.iss`:

- set `desktopicon` selected by default;
- add `autostart`, selected by default;
- set `appliancepower` to `Flags: unchecked`;
- point Start Menu, desktop, and startup shortcuts to `runtime\pythonw.exe` with quoted `freetv.py start` parameters; the startup shortcut adds `--supervise`;
- run `runtime\python.exe "{app}\freetv.py" setup` with `SW_HIDE` and `ewWaitUntilTerminated` during `ssPostInstall`;
- only after a zero exit code, delete the legacy `{app}\.venv` tree and old `PC TV Box` scheduled task;
- preserve and conditionally run the existing elevated power script only when selected and `/UPDATE` is not `1`;
- start FreeTV through `pythonw.exe` after successful setup;
- remove the `scripts\install.ps1` invocation;
- remove legacy PowerShell autostart cleanup from uninstall and let Inno remove its startup shortcut, while deleting the old scheduled task with hidden `schtasks.exe` for migration.

Every failure message must include `{log}` or the expanded setup-log path.

- [ ] **Step 5: Build and smoke the actual installer locally**

```powershell
./scripts/build-installer.ps1 -OutputPath ./FreeTV-Setup.exe
$installer = Get-Item ./FreeTV-Setup.exe
if ($installer.Length -gt 250MB) { throw "Installer exceeds 250 MiB." }
$process = Start-Process ./FreeTV-Setup.exe -ArgumentList @(
  '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
  '/TASKS="autostart,desktopicon,!appliancepower"',
  '/LOG=FreeTV-Setup.log'
) -PassThru -Wait
if ($process.ExitCode -ne 0) { throw "Installer failed: $($process.ExitCode)" }
$container = New-PesterContainer `
  -Path ./scripts/tests/installer.Tests.ps1 `
  -Data @{ InstallRoot = (Join-Path $env:LOCALAPPDATA 'FreeTV') }
$result = Invoke-Pester -Container $container -PassThru
if ($result.FailedCount -gt 0) { throw "$($result.FailedCount) installer checks failed." }
```

Expected: `%LOCALAPPDATA%\FreeTV\runtime\python.exe` exists, `.venv` does not, Start Menu/startup/desktop shortcuts target `runtime\pythonw.exe`, and the controller becomes healthy.

- [ ] **Step 6: Commit the installer**

```powershell
git add scripts/build-installer.ps1 installer/FreeTV.iss scripts/tests/installer.Tests.ps1
git commit -m "feat: install FreeTV fully offline"
```

### Task 5: Complete-Installer Windows Updates

**Files:**
- Modify: `backend/app/system/updater.py:1-258`
- Modify: `backend/app/installer.py:1-199`
- Modify: `freetv.py:17-126`
- Modify: `backend/tests/test_updater.py:1-253`
- Modify: `backend/tests/test_installer.py:40-230`

**Interfaces:**
- Extends: `UpdateInfo.artifact_kind: Literal["archive", "installer"]`.
- Produces: `pending_installer_marker(root: Path) -> Path`.
- Produces: `launch_pending_installer_update(root: Path, *, popen: Callable[..., object] = subprocess.Popen, os_name: str = os.name) -> bool`.
- Preserves: `apply_pending_update(root)` only for portable archive updates.

- [ ] **Step 1: Replace installer-mode test fixtures**

Add a bundled marker (`runtime/python.exe`) to a temp root and return Release assets named `FreeTV-Setup.exe` and `.sha256`. Assert:

```python
assert info is not None
assert info.artifact_kind == "installer"
assert info.download_url.endswith("/FreeTV-Setup.exe")
assert info.checksum_url.endswith("/FreeTV-Setup.exe.sha256")
```

Stage a small fake EXE through `httpx.MockTransport`, then assert `config/updates/pending-installer-update.json` contains the version, installer path, and exact digest. Keep a separate portable-root test expecting zip assets.

Add launcher validation tests that reject markers outside `config/updates`, reject a changed installer digest, and capture these exact arguments for a valid marker:

```text
/VERYSILENT
/SUPPRESSMSGBOXES
/NORESTART
/UPDATE=1
/MERGETASKS="!appliancepower"
```

- [ ] **Step 2: Run updater tests and verify the new expectations fail**

```powershell
python -m pytest backend/tests/test_updater.py backend/tests/test_installer.py -q
```

Expected: failures because `UpdateInfo` has no kind and all releases select zip assets.

- [ ] **Step 3: Stream installer updates to disk**

Add `MAX_INSTALLER_BYTES = 250 * 1024 * 1024`. Do not allocate the complete installer in memory. Implement:

```python
async def _download_file_limited(
    client: httpx.AsyncClient,
    url: str,
    destination: Path,
    *,
    maximum_bytes: int,
) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    async with client.stream("GET", url, follow_redirects=True) as response:
        # Reuse the existing trusted-host validation for history and final URL.
        response.raise_for_status()
        with destination.open("wb") as output:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > maximum_bytes:
                    raise ValueError("更新檔過大")
                digest.update(chunk)
                output.write(chunk)
    return size, digest.hexdigest()
```

In bundled mode, discover exact installer assets, stream to a `.tmp` file under `config/updates`, fetch the checksum with the existing small bounded helper, compare the digest, atomically rename the installer, and atomically write `pending-installer-update.json`. In portable mode, retain archive validation and `pending-update.json` behavior.

- [ ] **Step 4: Implement stdlib-only installer handoff**

In `backend/app/installer.py`, validate that the marker and source installer are regular files beneath `config/updates`, the size is bounded, and the recomputed SHA-256 matches. Copy the verified installer to a uniquely named file under `tempfile.gettempdir()/FreeTV-updates`, recheck the copy, then launch it detached with the five arguments above.

If the marker's target version equals the installed `VERSION`, delete the marker and source installer, attempt cleanup of old `FreeTV-update-*.exe` temp files, and continue normal startup. If the target is newer and launch succeeds, return `True`; do not import application dependencies.

At the top of `freetv.py`, before `apply_pending_update`:

```python
if launch_pending_installer_update(ROOT):
    raise SystemExit(0)
UPDATE_APPLIED = apply_pending_update(ROOT)
```

- [ ] **Step 5: Run the focused updater suite**

```powershell
python -m pytest backend/tests/test_updater.py backend/tests/test_installer.py -q
```

Expected: installer and portable branches pass; untrusted redirects, size overflow, checksum mismatch, path escape, and tampered-marker tests all fail closed.

- [ ] **Step 6: Commit installer-based updates**

```powershell
git add freetv.py backend/app/installer.py backend/app/system/updater.py backend/tests/test_installer.py backend/tests/test_updater.py
git commit -m "feat: update Windows with full installer"
```

### Task 6: Release Pipeline and User Documentation

**Files:**
- Modify: `.github/workflows/release.yml:90-383`
- Modify: `README.md:5-95`
- Modify: `docs/WINDOWS_SETUP.md`

**Interfaces:**
- Release assets remain `FreeTV-Setup.exe`, `.sha256`, portable zip/checksum, cross-platform installers, and manifest.
- Installer smoke proves the installed process uses `%LOCALAPPDATA%\FreeTV\runtime\python.exe` and no `.venv`.

- [ ] **Step 1: Make the release package job build exact prerequisites**

Install Inno Setup and 7-Zip in the package job, set up Python `3.13`, and call the modified `build-installer.ps1`. Reject output above 250 MiB before hashing. Keep the existing portable zip build and smoke separate.

- [ ] **Step 2: Convert installer smoke to offline behavior**

Before launching the installer, set process-local invalid proxies:

```powershell
$env:HTTP_PROXY = 'http://127.0.0.1:9'
$env:HTTPS_PROXY = 'http://127.0.0.1:9'
$env:NO_PROXY = '127.0.0.1,localhost'
```

Install with `!appliancepower`, verify `runtime\python.exe`, `tools\mpv\mpv.exe`, and `tools\cloudflared\cloudflared.exe`, assert `.venv` is absent, then start:

```powershell
& $installed\runtime\python.exe $installed\freetv.py start --no-browser --no-tunnel
& $installed\runtime\python.exe $installed\scripts\integration-smoke.py `
  --transport http --port 8765 --lan-ip 127.0.0.1
```

Inspect the controller process command line and require the executable path to live under `runtime`. Remove old assertions that the installer created `.venv` or configured appliance power by default.

- [ ] **Step 3: Focus the Release and README presentation**

Generate release notes with this first section before the changelog:

```markdown
## Windows 10/11 x64

Download **FreeTV-Setup.exe** and double-click it. Installation is per-user and does not require Python or an Internet connection. Windows may show an unknown-publisher warning because this release is not Authenticode-signed; verify `FreeTV-Setup.exe.sha256` when authenticity matters.

## Other platforms and advanced downloads
```

Mirror that ordering in `README.md`. State that Chrome and online services still need Internet when used, the installer itself does not. Remove wording that recommended Windows installation may use winget/pip. Document bundled mpv/cloudflared, the optional UAC power task, installer-based updates, and configuration preservation.

- [ ] **Step 4: Run the project verification used by release jobs**

```powershell
python -m pytest backend/tests -q
Push-Location frontend
npm ci
npm run lint
npm run build
npm test
Pop-Location
Import-Module Pester -MinimumVersion 5.0 -Force
$result = Invoke-Pester -Path ./scripts/tests/startup.Tests.ps1 -PassThru
if ($result.FailedCount -gt 0) { throw "$($result.FailedCount) Pester tests failed." }
./scripts/build-installer.ps1 -OutputPath ./FreeTV-Setup.exe
```

Expected: all tests pass, frontend builds, Pester passes, and the installer is at most 250 MiB.

- [ ] **Step 5: Commit release automation and docs**

```powershell
git add .github/workflows/release.yml README.md docs/WINDOWS_SETUP.md
git commit -m "ci: verify offline Windows installation"
```

### Task 7: Release Candidate Review

**Files:**
- Modify: any files identified by the focused verification only when the failure belongs to this feature.
- Modify: `VERSION`

**Interfaces:**
- Produces release candidate version `0.5.0` and tag `v0.5.0`.

- [ ] **Step 1: Set and verify version 0.5.0**

Write exactly `0.5.0` plus newline to `VERSION`. Run the release commands from Task 6 and the actual local installer smoke from Task 4.

- [ ] **Step 2: Review the complete changed surface**

Confirm every removed API has no caller, every bundled artifact is pinned, `config` and `logs` are not part of managed replacement, no setup path downloads CRX/Python/packages, and the generated installer contains the private runtime and both tools.

- [ ] **Step 3: Commit the release version**

```powershell
git add VERSION
git commit -m "chore: prepare v0.5.0"
```

- [ ] **Step 4: Tag, push, and wait for the tested release**

```powershell
git tag -a v0.5.0 -m "FreeTV v0.5.0"
git push origin main
git push origin v0.5.0
Start-Sleep -Seconds 5
$runId = gh run list --repo 1122-gggggg/freetv --workflow Release --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch $runId --repo 1122-gggggg/freetv --exit-status
```

Expected: Release workflow succeeds and publishes `FreeTV-Setup.exe` plus its checksum.

### Task 8: Clean-Machine Installation Acceptance

**Files:**
- No repository file changes.

**Interfaces:**
- Consumes: published v0.5.0 installer and checksum.
- Produces: observed clean-machine installation evidence.

- [ ] **Step 1: Prepare the clean target**

Use a clean Windows 10/11 x64 physical machine or disposable local VM with no Python, Node.js, mpv, cloudflared, or prior `%LOCALAPPDATA%\FreeTV`. Download or transfer the v0.5.0 installer and checksum, verify SHA-256, then disconnect Internet while leaving the private LAN available.

- [ ] **Step 2: Install through the normal wizard**

Double-click `FreeTV-Setup.exe`, keep autostart and desktop shortcut selected, leave appliance power mode unselected, and finish installation. Observe that no PowerShell/console window, Python installer, winget, pip, unexpected UAC, or network requirement appears.

- [ ] **Step 3: Exercise the installed application**

Start FreeTV from its installed shortcut. Verify the TV page opens, pair a phone on the LAN, and exercise navigation. Prove the offline mpv payload independently with `& \"$env:LOCALAPPDATA\FreeTV\tools\mpv\mpv.exe\" --version`; do not require an Internet-backed TV stream while the machine is offline.

On the target, collect exact state:

```powershell
$root = Join-Path $env:LOCALAPPDATA 'FreeTV'
Get-Content (Join-Path $root 'VERSION')
Test-Path (Join-Path $root '.venv')
Test-Path (Join-Path $root 'runtime\pythonw.exe')
Test-Path (Join-Path $root 'tools\mpv\mpv.exe')
Test-Path (Join-Path $root 'tools\cloudflared\cloudflared.exe')
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

Expected: version `0.5.0`; `.venv` is `False`; all three bundled executable checks are `True`; health reports backend and frontend ready.

- [ ] **Step 4: Keep this installation for the update acceptance**

Create a recognizable harmless user setting in `config/settings.json` and record its exact value. Reconnect Internet. Do not reinstall or modify application files manually.

### Task 9: Real User-Side Patch Update

**Files:**
- Modify: `VERSION`
- Modify: `README.md`

**Interfaces:**
- Produces release version `0.5.1` and tag `v0.5.1`.
- Proves update initiated by the installed v0.5.0 user interface.

- [ ] **Step 1: Create a deliberately small observable update**

Change `VERSION` from `0.5.0` to `0.5.1`. Add one release note line under the Windows installation section:

```text
The v0.5.1 patch validates complete-installer updates from an installed v0.5.0 client.
```

Do not change updater behavior in this patch; the purpose is to test the already-implemented path.

- [ ] **Step 2: Verify, commit, tag, and publish v0.5.1**

Run the Task 6 verification and build. Then:

```powershell
git add VERSION README.md
git commit -m "chore: prepare v0.5.1 update proof"
git tag -a v0.5.1 -m "FreeTV v0.5.1"
git push origin main
git push origin v0.5.1
Start-Sleep -Seconds 5
$runId = gh run list --repo 1122-gggggg/freetv --workflow Release --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch $runId --repo 1122-gggggg/freetv --exit-status
```

Expected: v0.5.1 publishes a new full installer and checksum.

- [ ] **Step 3: Trigger the update as the installed user**

On the untouched v0.5.0 clean-machine installation, wait for or restart FreeTV to trigger release discovery. Use the TV or paired Remote update action. Confirm it reports that the update was downloaded and a restart is required. Restart FreeTV normally; do not run the installer manually.

- [ ] **Step 4: Verify the completed update**

Run on the target:

```powershell
$root = Join-Path $env:LOCALAPPDATA 'FreeTV'
Get-Content (Join-Path $root 'VERSION')
Test-Path (Join-Path $root '.venv')
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

Expected: version `0.5.1`; `.venv` remains `False`; health is ready; the recorded user setting is unchanged; no UAC or manual installer action occurred. Confirm the installed README contains the v0.5.1 proof line.

- [ ] **Step 5: Completion gate**

Only after both Task 8 and Task 9 pass, report the exact installer sizes, release URLs, clean-machine health result, installed runtime/tool paths, preserved setting, and observed v0.5.0 → v0.5.1 transition. A CI-only result is insufficient.
