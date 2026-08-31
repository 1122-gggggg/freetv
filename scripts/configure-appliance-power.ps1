[CmdletBinding()]
param(
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw 'Appliance power configuration is available only on Windows.'
}

$PowerCfg = (Get-Command powercfg.exe -ErrorAction Stop).Source
$LidSubgroupGuid = '4f971e89-eebd-4455-a8de-9e59040e7347'
$LidActionGuid = '5ca83367-6e45-459f-a27b-476b1d01c936'
$Settings = @(
    @{ Subgroup = 'SUB_BUTTONS'; Setting = 'LIDACTION' },
    @{ Subgroup = 'SUB_SLEEP'; Setting = 'STANDBYIDLE' },
    @{ Subgroup = 'SUB_SLEEP'; Setting = 'HIBERNATEIDLE' }
)

function Invoke-PowerCfg {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $Output = @(& $PowerCfg @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "powercfg $($Arguments -join ' ') failed: $($Output -join ' ')"
    }
    return $Output
}

function Assert-PowerSettingDisabled {
    param(
        [Parameter(Mandatory)][string]$Subgroup,
        [Parameter(Mandatory)][string]$Setting
    )

    $Output = Invoke-PowerCfg -Arguments @('/QUERY', 'SCHEME_CURRENT', $Subgroup, $Setting)
    $Values = @(
        [regex]::Matches(($Output -join "`n"), '(?i)0x([0-9a-f]{8})') |
            ForEach-Object { [Convert]::ToUInt32($_.Groups[1].Value, 16) }
    )
    if ($Values.Count -lt 2 -or $Values[-2] -ne 0 -or $Values[-1] -ne 0) {
        throw "$Subgroup/$Setting is not disabled for both AC and battery power."
    }
}

Invoke-PowerCfg -Arguments @(
    '/ATTRIBUTES',
    $LidSubgroupGuid,
    $LidActionGuid,
    '-ATTRIB_HIDE'
) | Out-Null

if (-not $VerifyOnly) {
    foreach ($PowerSetting in $Settings) {
        Invoke-PowerCfg -Arguments @(
            '/SETACVALUEINDEX',
            'SCHEME_CURRENT',
            $PowerSetting.Subgroup,
            $PowerSetting.Setting,
            '0'
        ) | Out-Null
        Invoke-PowerCfg -Arguments @(
            '/SETDCVALUEINDEX',
            'SCHEME_CURRENT',
            $PowerSetting.Subgroup,
            $PowerSetting.Setting,
            '0'
        ) | Out-Null
    }
    Invoke-PowerCfg -Arguments @('/SETACTIVE', 'SCHEME_CURRENT') | Out-Null
}

foreach ($PowerSetting in $Settings) {
    Assert-PowerSettingDisabled @PowerSetting
}

Write-Output 'FreeTV appliance power settings verified: lid close, sleep, and hibernation stay disabled on AC and battery power.'
