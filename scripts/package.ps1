[CmdletBinding()]
param(
    [string]$OutputPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$FrontendIndex = Join-Path $Root 'frontend\dist\index.html'
if (-not (Test-Path -LiteralPath $FrontendIndex)) {
    throw 'frontend\dist\index.html is missing. Build the frontend first, or download pc-tv-box.zip from GitHub Releases.'
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $Root 'pc-tv-box.zip'
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

$StageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pc-tv-box-stage-" + [guid]::NewGuid().ToString('N'))
$Stage = Join-Path $StageRoot 'pc-tv-box'
try {
    New-Item -ItemType Directory -Force -Path @(
        (Join-Path $Stage 'frontend'),
        (Join-Path $Stage 'backend'),
        (Join-Path $Stage 'scripts'),
        (Join-Path $Stage 'config'),
        (Join-Path $Stage 'docs')
    ) | Out-Null

    Copy-Item -Recurse (Join-Path $Root 'frontend\dist') (Join-Path $Stage 'frontend\dist')
    Copy-Item -Recurse (Join-Path $Root 'backend\app') (Join-Path $Stage 'backend\app')
    Copy-Item (Join-Path $Root 'backend\requirements.txt') (Join-Path $Stage 'backend\')
    Copy-Item (Join-Path $Root 'scripts\*.ps1') (Join-Path $Stage 'scripts\')
    Copy-Item (Join-Path $Root 'scripts\*.psm1') (Join-Path $Stage 'scripts\')
    Copy-Item (Join-Path $Root 'scripts\integration-smoke.py') (Join-Path $Stage 'scripts\')
    Copy-Item (Join-Path $Root 'config\settings.example.json') (Join-Path $Stage 'config\')
    Copy-Item (Join-Path $Root 'config\channels.example.json') (Join-Path $Stage 'config\')
    Copy-Item (Join-Path $Root 'config\news.example.json') (Join-Path $Stage 'config\')
    Copy-Item (Join-Path $Root 'README.md') $Stage
    Copy-Item (Join-Path $Root 'docs\*.md') (Join-Path $Stage 'docs\')

    Get-ChildItem -Path $Stage -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force

    if (Test-Path -LiteralPath $OutputPath) {
        Remove-Item -LiteralPath $OutputPath -Force
    }
    Compress-Archive -Path $Stage -DestinationPath $OutputPath -Force
    Write-Host "Wrote $OutputPath"
}
finally {
    if (Test-Path -LiteralPath $StageRoot) {
        Remove-Item -LiteralPath $StageRoot -Recurse -Force
    }
}
