[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'TVBox.Startup.psm1') -Force

$Root = Split-Path -Parent $PSScriptRoot

function Assert-NativeSuccess {
    param([string]$Action)

    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

function Get-PythonRuntimeProbe {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [string[]]$PrefixArguments = @(),

        [Parameter(Mandatory = $true)]
        [string]$DisplayName
    )

    $ProbeArguments = @($PrefixArguments) + @(
        '-c',
        'import json, sys; print(json.dumps({''version'': ''.''.join(str(part) for part in sys.version_info[:3]), ''prefix'': sys.prefix, ''base_prefix'': sys.base_prefix}))'
    )
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $VersionOutput = & $Executable @ProbeArguments 2>$null
        $ProbeExitCode = $LASTEXITCODE
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ProbeExitCode -ne 0) {
        return $null
    }

    try {
        $RuntimeMetadata = ([string](@($VersionOutput) | Select-Object -Last 1)) | ConvertFrom-Json
        $Version = [version]([string]$RuntimeMetadata.version)
    } catch {
        return $null
    }
    return [PSCustomObject]@{
        Executable      = $Executable
        PrefixArguments = @($PrefixArguments)
        DisplayName     = $DisplayName
        Version         = $Version
        Prefix          = [string]$RuntimeMetadata.prefix
        BasePrefix      = [string]$RuntimeMetadata.base_prefix
    }
}

$Npm = Get-Command npm -ErrorAction SilentlyContinue
$SettingsPath = Join-Path $Root 'config\settings.json'
$SettingsSource = if (Test-Path $SettingsPath) { $SettingsPath } else { Join-Path $Root 'config\settings.example.json' }
$RawSettings = Get-Content -Raw -Path $SettingsSource | ConvertFrom-Json
$Transport = (Get-StartupSettings -Settings $RawSettings).Transport

$MinimumPythonVersion = [version]'3.11'
$VenvDirectory = Join-Path $Root '.venv'
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $VenvDirectory) {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        throw 'Existing .venv is incomplete and was not changed. Remove or rename .venv manually, then re-run setup.ps1.'
    }
    $ExistingVenvRuntime = Get-PythonRuntimeProbe `
        -Executable $VenvPython `
        -DisplayName 'existing .venv Python'
    if ($null -eq $ExistingVenvRuntime) {
        throw 'Existing .venv Python could not run and was not changed. Remove or rename .venv manually, then re-run setup.ps1.'
    }
    if (-not (Test-PythonRuntimeVersion `
        -VersionValue $ExistingVenvRuntime.Version `
        -MinimumVersion $MinimumPythonVersion)) {
        throw "Existing .venv uses Python $($ExistingVenvRuntime.Version), but Python 3.11 or newer is required. The environment was not changed; remove or rename .venv manually, then re-run setup.ps1."
    }
    if (-not (Test-PythonVirtualEnvironmentRuntime `
        -Runtime $ExistingVenvRuntime `
        -ExpectedDirectory $VenvDirectory `
        -MinimumVersion $MinimumPythonVersion)) {
        throw 'Existing .venv Python is not isolated to this project and was not changed. Remove or rename .venv manually, then re-run setup.ps1.'
    }
    Write-Host "Using existing .venv Python $($ExistingVenvRuntime.Version)."
} else {
    $RuntimeCandidates = @()
    $PathPython = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $PathPython) {
        $Candidate = Get-PythonRuntimeProbe `
            -Executable $PathPython.Source `
            -DisplayName 'python on PATH'
        if ($null -ne $Candidate) {
            $RuntimeCandidates += $Candidate
        }
    }

    $PyLauncher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $PyLauncher) {
        $LauncherProbes = @(
            [PSCustomObject]@{ DisplayName = 'py -3.11'; PrefixArguments = @('-3.11') },
            [PSCustomObject]@{ DisplayName = 'py -3'; PrefixArguments = @('-3') }
        )
        foreach ($LauncherProbe in $LauncherProbes) {
            $Candidate = Get-PythonRuntimeProbe `
                -Executable $PyLauncher.Source `
                -PrefixArguments $LauncherProbe.PrefixArguments `
                -DisplayName $LauncherProbe.DisplayName
            if ($null -ne $Candidate) {
                $RuntimeCandidates += $Candidate
            }
        }
    }

    $SelectedRuntime = Select-PythonRuntimeCandidate `
        -Candidates $RuntimeCandidates `
        -MinimumVersion $MinimumPythonVersion
    if ($null -eq $SelectedRuntime) {
        $DetectedRuntimes = @(
            $RuntimeCandidates | ForEach-Object { "$($_.DisplayName): Python $($_.Version)" }
        ) -join ', '
        if ([string]::IsNullOrWhiteSpace($DetectedRuntimes)) {
            $DetectedRuntimes = 'none'
        }
        throw "Python 3.11 or newer is required through 'python' on PATH or the Windows 'py' launcher; detected: $DetectedRuntimes. Install it from https://www.python.org/downloads/windows/."
    }

    Write-Host "Creating Python virtual environment with $($SelectedRuntime.DisplayName) (Python $($SelectedRuntime.Version))..."
    $CreateVenvArguments = @($SelectedRuntime.PrefixArguments) + @('-m', 'venv', $VenvDirectory)
    & $SelectedRuntime.Executable @CreateVenvArguments
    Assert-NativeSuccess 'Creating Python virtual environment'

    $CreatedVenvRuntime = Get-PythonRuntimeProbe `
        -Executable $VenvPython `
        -DisplayName 'new .venv Python'
    if (
        -not (Test-PythonVirtualEnvironmentRuntime `
            -Runtime $CreatedVenvRuntime `
            -ExpectedDirectory $VenvDirectory `
            -MinimumVersion $MinimumPythonVersion)
    ) {
        throw 'The new .venv does not contain a usable Python 3.11+ runtime. It was not deleted; inspect or remove it manually before retrying.'
    }
}

Write-Host 'Installing backend dependencies...'
& $VenvPython -m pip install --upgrade pip
Assert-NativeSuccess 'Upgrading pip'
& $VenvPython -m pip install -r (Join-Path $Root 'backend\requirements.txt')
Assert-NativeSuccess 'Installing backend dependencies'

$AdblockDirectory = Join-Path $Root 'vendor\adblock'
Push-Location (Join-Path $Root 'backend')
try {
    & $VenvPython -m app.applications.adblock --directory $AdblockDirectory
    Assert-NativeSuccess 'Installing AdBlock extension'
} finally {
    Pop-Location
}

$FrontendIndex = Join-Path $Root 'frontend\dist\index.html'
if (Test-Path $FrontendIndex) {
    Write-Host 'Frontend build found at frontend\dist; skipping npm install and build.'
} else {
    if (-not $Npm) {
        throw 'Frontend build not found. Use the pc-tv-box.zip GitHub Release (includes frontend\dist) or install Node.js LTS and re-run setup.'
    }
    Push-Location (Join-Path $Root 'frontend')
    try {
        & $Npm.Source ci
        Assert-NativeSuccess 'Installing frontend dependencies'
        Write-Host 'Building frontend...'
        & $Npm.Source run build
        Assert-NativeSuccess 'Building frontend'
    } finally {
        Pop-Location
    }
}

foreach ($Name in @('settings', 'channels', 'news')) {
    $Example = Join-Path $Root "config\$Name.example.json"
    $Local = Join-Path $Root "config\$Name.json"
    if (-not (Test-Path $Local)) {
        Copy-Item $Example $Local
        Write-Host "Created local config: config\$Name.json"
    }
}

if ($Transport -eq 'https') {
    $TlsDirectory = Join-Path $Root 'config\tls'
    $TlsOutput = $null
    Push-Location (Join-Path $Root 'backend')
    try {
        $TlsOutput = & $VenvPython -m app.security.tls --directory $TlsDirectory
        Assert-NativeSuccess 'Creating local TLS materials'
    } finally {
        Pop-Location
    }
    try {
        $Tls = (($TlsOutput -join "`n") | ConvertFrom-Json)
    } catch {
        throw 'Could not read locally generated TLS material metadata.'
    }
    if (-not (Test-Path $Tls.ca_certificate) -or -not (Test-Path $Tls.certificate) -or -not (Test-Path $Tls.private_key)) {
        throw 'Local TLS material generation did not produce the expected certificate files.'
    }

    Write-Warning 'The controller uses HTTPS. Import this CA manually into the current user Trusted Root Certification Authorities store before opening the TV Launcher.'
    Write-Host "Local TLS CA: $($Tls.ca_certificate)"
    Write-Host "CA SHA-256: $($Tls.ca_sha256)"
}

$ChromeCandidates = @(
    'C:\Program Files\Google\Chrome\Application\chrome.exe',
    'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
)
$BraveCandidates = @(
    'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',
    (Join-Path $env:LOCALAPPDATA 'BraveSoftware\Brave-Browser\Application\brave.exe')
)
$EdgeCandidates = @(
    'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
)
$Chrome = Get-Command chrome.exe -ErrorAction SilentlyContinue
$ChromeFound = if ($Chrome) { $Chrome.Source } else { $ChromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1 }
$Mpv = Get-Command mpv.exe -ErrorAction SilentlyContinue
$BraveFound = $BraveCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$EdgeFound = $EdgeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

Write-Host ''
Write-Host 'External dependency check:'
Write-Host ("  Chrome: {0}" -f $(if ($ChromeFound) { $ChromeFound } else { 'not found; install Google Chrome for YouTube & News' }))
Write-Host ("  Brave:  {0}" -f $(if ($BraveFound) { $BraveFound } else { 'not found; configure applications.brave_path if installed elsewhere' }))
Write-Host ("  Edge:   {0}" -f $(if ($EdgeFound) { $EdgeFound } else { 'not found; install Microsoft Edge' }))
$Cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($Cloudflared) {
    Write-Host "  cloudflared: $($Cloudflared.Source)"
} else {
    Write-Warning 'cloudflared was not found. Off-LAN Remote needs: winget install Cloudflare.cloudflared'
}
if ($Mpv) {
    Write-Host "  mpv:   $($Mpv.Source)"
} else {
    Write-Warning 'mpv was not found. Live TV remains unavailable until mpv is installed and applications.mpv_path is configured.'
    Write-Host '  Install guide: https://mpv.io/installation/'
}

Write-Host ''
Write-Host $(if ($Transport -eq 'https') { 'Setup complete. Trust the local CA on this Windows user and each phone, then start the TV controller with .\scripts\start.ps1' } else { 'Setup complete. Start the TV controller with .\scripts\start.ps1' })
