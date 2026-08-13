[CmdletBinding()]
param(
    [switch]$Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$TaskName = 'PC TV Box'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host 'Removed PC TV Box autostart task.'
    exit 0
}

$StartScript = Join-Path $Root 'scripts\start.ps1'
if (-not (Test-Path $StartScript)) { throw "Start script was not found: $StartScript" }

$Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartScript`""
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Starts the per-user PC TV Box controller after Windows sign-in.' -Force | Out-Null
Write-Host 'Installed PC TV Box autostart for the current user. Remove it with .\scripts\install-autostart.ps1 -Remove'
