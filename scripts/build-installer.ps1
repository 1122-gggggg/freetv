[CmdletBinding()]
param(
    [string]$OutputPath = '',
    [string]$PackagePath = '',
    [string]$IsccPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Resolve-InnoCompiler([string]$RequestedPath) {
    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        $resolved = Resolve-Path -LiteralPath $RequestedPath -ErrorAction Stop
        return $resolved.Path
    }

    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }

    throw 'Inno Setup 6 was not found. Install it with: winget install JRSoftware.InnoSetup'
}

$Compiler = Resolve-InnoCompiler $IsccPath
$Version = (Get-Content -Raw -LiteralPath (Join-Path $Root 'VERSION')).Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "VERSION is not a valid semantic version: $Version"
}
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $Root 'FreeTV-Setup.exe'
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

$StageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("freetv-installer-stage-" + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Force -Path $StageRoot | Out-Null
    if ([string]::IsNullOrWhiteSpace($PackagePath)) {
        $PackagePath = Join-Path $StageRoot 'pc-tv-box.zip'
        & (Join-Path $PSScriptRoot 'package.ps1') -OutputPath $PackagePath
    } else {
        $PackagePath = (Resolve-Path -LiteralPath $PackagePath -ErrorAction Stop).Path
    }

    $BundleRoot = Join-Path $StageRoot 'offline-bundle'
    & (Join-Path $PSScriptRoot 'build-offline-bundle.ps1') `
        -PackagePath $PackagePath `
        -OutputPath $BundleRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'Offline bundle assembly failed.'
    }
    $SourceRoot = $BundleRoot

    $CompilerOutput = Join-Path $StageRoot 'output'
    New-Item -ItemType Directory -Force -Path $CompilerOutput | Out-Null
    & $Compiler `
        "/DSourceRoot=$SourceRoot" `
        "/DAppVersion=$Version" `
        "/DOutputDir=$CompilerOutput" `
        (Join-Path $Root 'installer\FreeTV.iss')
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compiler failed with exit code $LASTEXITCODE."
    }

    $CompiledInstaller = Join-Path $CompilerOutput 'FreeTV-Setup.exe'
    if (-not (Test-Path -LiteralPath $CompiledInstaller)) {
        throw 'Inno Setup completed without producing FreeTV-Setup.exe.'
    }
    $OutputDirectory = Split-Path -Parent $OutputPath
    if (-not [string]::IsNullOrWhiteSpace($OutputDirectory)) {
        New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
    }
    Copy-Item -LiteralPath $CompiledInstaller -Destination $OutputPath -Force
    Write-Host "Wrote $OutputPath"
}
finally {
    if (Test-Path -LiteralPath $StageRoot) {
        Remove-Item -LiteralPath $StageRoot -Recurse -Force
    }
}
