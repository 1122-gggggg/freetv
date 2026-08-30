@echo off
setlocal EnableExtensions EnableDelayedExpansion
if not exist "%~dp0freetv.py" goto download_installer
if not exist "%~dp0VERSION" goto download_installer
if not exist "%~dp0scripts\install.ps1" goto download_installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
exit /b %errorlevel%

:download_installer
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $base='https://github.com/1122-gggggg/freetv/releases/latest/download'; $temp=Join-Path ([IO.Path]::GetTempPath()) ('freetv-install-'+[guid]::NewGuid().ToString('N')); try { New-Item -ItemType Directory -Path $temp | Out-Null; $zip=Join-Path $temp 'pc-tv-box.zip'; $sum=Join-Path $temp 'pc-tv-box.zip.sha256'; Invoke-WebRequest -UseBasicParsing -Uri ($base+'/pc-tv-box.zip') -OutFile $zip; Invoke-WebRequest -UseBasicParsing -Uri ($base+'/pc-tv-box.zip.sha256') -OutFile $sum; $expected=((Get-Content -Raw -LiteralPath $sum).Trim() -split '\s+')[0].ToLowerInvariant(); $actual=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant(); if ($expected -notmatch '^[0-9a-f]{64}$' -or $actual -ne $expected) { throw 'FreeTV installer checksum verification failed.' }; Expand-Archive -LiteralPath $zip -DestinationPath $temp; & (Join-Path $temp 'pc-tv-box\scripts\install.ps1'); exit $LASTEXITCODE } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue } }"
exit /b !errorlevel!
