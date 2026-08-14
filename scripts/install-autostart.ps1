[CmdletBinding()]
param(
    [switch]$Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'TVBox.Startup.psm1') -Force

$Root = Split-Path -Parent $PSScriptRoot
$TaskName = 'PC TV Box'

if ($Remove) {
    Remove-AutostartTask -TaskName $TaskName
    Write-Host 'Removed PC TV Box autostart task.'
    exit 0
}

$StartScript = Join-Path $Root 'scripts\start.ps1'
if (-not (Test-Path -LiteralPath $StartScript)) { throw "Start script was not found: $StartScript" }

Install-AutostartTask -StartScriptPath $StartScript -TaskName $TaskName
Write-Host 'Installed PC TV Box autostart for the current user. Remove it with .\scripts\install-autostart.ps1 -Remove'
