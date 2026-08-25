[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$StartArguments
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Setup = Join-Path $PSScriptRoot 'scripts\setup.ps1'
$Start = Join-Path $PSScriptRoot 'scripts\start.ps1'
& $Setup
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
    throw "Setup failed with exit code $LASTEXITCODE."
}
if ($StartArguments) {
    & $Start @StartArguments
} else {
    & $Start
}
