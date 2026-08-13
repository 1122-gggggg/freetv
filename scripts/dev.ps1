[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Python virtual environment was not found. Run .\scripts\setup.ps1 first.' }

$Listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $Listener) {
    Start-Process -FilePath $Python -WorkingDirectory (Join-Path $Root 'backend') -ArgumentList @(
        '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8765', '--ws', 'websockets-sansio', '--reload'
    ) | Out-Null
}

Push-Location (Join-Path $Root 'frontend')
try {
    Write-Host 'Vite development server: http://127.0.0.1:5173/tv'
    & npm run dev -- --host 127.0.0.1
} finally {
    Pop-Location
}
