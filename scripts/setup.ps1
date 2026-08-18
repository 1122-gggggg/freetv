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

$Python = Get-Command python -ErrorAction SilentlyContinue
$Node = Get-Command node -ErrorAction SilentlyContinue
$Npm = Get-Command npm -ErrorAction SilentlyContinue
$SettingsPath = Join-Path $Root 'config\settings.json'
$SettingsSource = if (Test-Path $SettingsPath) { $SettingsPath } else { Join-Path $Root 'config\settings.example.json' }
$RawSettings = Get-Content -Raw -Path $SettingsSource | ConvertFrom-Json
$Transport = (Get-StartupSettings -Settings $RawSettings).Transport

if (-not $Python) { throw 'Python 3.11 or newer is required. Install it from https://www.python.org/downloads/windows/.' }

$PythonVersionText = (& $Python.Source --version 2>&1).ToString().Trim()
Assert-NativeSuccess 'Checking Python version'
$PythonVersion = [version]($PythonVersionText -replace '^Python\s+', '')
if ($PythonVersion -lt [version]'3.11') { throw "Python 3.11 or newer is required; found $PythonVersionText." }

$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    Write-Host 'Creating Python virtual environment...'
    & $Python.Source -m venv (Join-Path $Root '.venv')
    Assert-NativeSuccess 'Creating Python virtual environment'
}

Write-Host 'Installing backend dependencies...'
& $VenvPython -m pip install --upgrade pip
Assert-NativeSuccess 'Upgrading pip'
& $VenvPython -m pip install -r (Join-Path $Root 'backend\requirements.txt')
Assert-NativeSuccess 'Installing backend dependencies'

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

foreach ($Name in @('settings', 'channels')) {
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

$BraveCandidates = @(
    'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',
    (Join-Path $env:LOCALAPPDATA 'BraveSoftware\Brave-Browser\Application\brave.exe')
)
$EdgeCandidates = @(
    'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
)
$Mpv = Get-Command mpv.exe -ErrorAction SilentlyContinue
$BraveFound = $BraveCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$EdgeFound = $EdgeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

Write-Host ''
Write-Host 'External dependency check:'
Write-Host ("  Brave: {0}" -f $(if ($BraveFound) { $BraveFound } else { 'not found; configure applications.brave_path if installed elsewhere' }))
Write-Host ("  Edge:  {0}" -f $(if ($EdgeFound) { $EdgeFound } else { 'not found; install Microsoft Edge' }))
if ($Mpv) {
    Write-Host "  mpv:   $($Mpv.Source)"
} else {
    Write-Warning 'mpv was not found. Live TV remains unavailable until mpv is installed and applications.mpv_path is configured.'
    Write-Host '  Install guide: https://mpv.io/installation/'
}

Write-Host ''
Write-Host $(if ($Transport -eq 'https') { 'Setup complete. Trust the local CA on this Windows user and each phone, then start the TV controller with .\scripts\start.ps1' } else { 'Setup complete. Start the TV controller with .\scripts\start.ps1' })
