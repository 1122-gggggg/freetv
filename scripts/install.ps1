Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Find-PythonLauncher {
    $command = Get-Command py -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Launcher\py.exe'),
        (Join-Path $env:WINDIR 'py.exe')
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Test-FreeTVPython([string]$Launcher) {
    if ([string]::IsNullOrWhiteSpace($Launcher)) { return $false }
    & $Launcher -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'
    return $LASTEXITCODE -eq 0
}

$py = Find-PythonLauncher
if (-not (Test-FreeTVPython $py)) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { throw 'Python 3.11+ is required; install Python or winget and retry.' }
    & $winget.Source install --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget failed to install Python (exit $LASTEXITCODE)." }
    $py = Find-PythonLauncher
    if (-not (Test-FreeTVPython $py)) { throw 'Python 3.11+ was installed but is not available yet. Sign out and retry.' }
}
& $py -3 "$root\freetv.py" install
exit $LASTEXITCODE
