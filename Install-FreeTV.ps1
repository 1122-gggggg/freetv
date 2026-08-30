[CmdletBinding()]
param(
    [string]$ReleaseBase = 'https://github.com/1122-gggggg/freetv/releases/latest/download'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("freetv-install-" + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $temporary | Out-Null
    $archive = Join-Path $temporary 'pc-tv-box.zip'
    $checksumFile = Join-Path $temporary 'pc-tv-box.zip.sha256'
    Invoke-WebRequest -UseBasicParsing -Uri "$ReleaseBase/pc-tv-box.zip" -OutFile $archive
    Invoke-WebRequest -UseBasicParsing -Uri "$ReleaseBase/pc-tv-box.zip.sha256" -OutFile $checksumFile

    $expected = ((Get-Content -LiteralPath $checksumFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expected -notmatch '^[0-9a-f]{64}$' -or $actual -ne $expected) {
        throw 'FreeTV installer checksum verification failed.'
    }

    Expand-Archive -LiteralPath $archive -DestinationPath $temporary
    $installer = Join-Path $temporary 'pc-tv-box\scripts\install.ps1'
    if (-not (Test-Path -LiteralPath $installer)) {
        throw 'The official FreeTV package does not contain scripts/install.ps1.'
    }
    & $installer
    exit $LASTEXITCODE
}
finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
    }
}
