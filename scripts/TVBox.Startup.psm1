Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-OptionalSetting {
    [CmdletBinding()]
    param(
        [PSObject]$Target,
        [string]$PropertyName,
        $Default = $null
    )

    if ($null -eq $Target -or $null -eq $Target.PSObject) {
        return $Default
    }
    $Property = $Target.PSObject.Properties[$PropertyName]
    if ($null -eq $Property -or $null -eq $Property.Value) {
        return $Default
    }
    return $Property.Value
}

function Get-StartupSettings {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [PSObject]$Settings
    )

    $Server = Get-OptionalSetting -Target $Settings -PropertyName 'server'
    if ($null -eq $Server) {
        throw 'Configured server settings are required.'
    }

    $PortRaw = Get-OptionalSetting -Target $Server -PropertyName 'port'
    if ($null -eq $PortRaw) {
        throw 'Configured server port is required.'
    }
    $Port = [int]$PortRaw
    if ($Port -lt 1 -or $Port -gt 65535) {
        throw "Configured server port is invalid: $Port"
    }

    $BindHost = [string](Get-OptionalSetting -Target $Server -PropertyName 'host' -Default '')
    if ($BindHost -ne '0.0.0.0') {
        throw 'Configured server host must be 0.0.0.0 for the authenticated LAN Remote.'
    }

    $HealthHost = '127.0.0.1'

    $Applications = Get-OptionalSetting -Target $Settings -PropertyName 'applications'
    $ConfiguredEdgePath = ''
    if ($null -ne $Applications) {
        $ConfiguredEdgePath = [string](Get-OptionalSetting -Target $Applications -PropertyName 'edge_path' -Default '')
    }

    return [PSCustomObject]@{
        Port               = $Port
        BindHost           = $BindHost
        HealthHost         = $HealthHost
        ConfiguredEdgePath = $ConfiguredEdgePath
    }
}

function Resolve-EdgeExecutable {
    [CmdletBinding()]
    param(
        [string]$ConfiguredPath = ''
    )

    if (-not [string]::IsNullOrWhiteSpace($ConfiguredPath) -and (Test-Path -LiteralPath $ConfiguredPath -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $ConfiguredPath).Path
    }

    $Candidates = @(
        'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
    )
    return $Candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}

function Get-EdgeUserDataDirectory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootDirectory
    )

    return [System.IO.Path]::GetFullPath((Join-Path $RootDirectory 'config\edge-profile'))
}

function Get-EdgeKioskArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,

        [Parameter(Mandatory = $true)]
        [string]$UserDataDir
    )

    return @(
        '--kiosk',
        $Url,
        '--edge-kiosk-type=fullscreen',
        '--no-first-run',
        "--user-data-dir=`"$UserDataDir`""
    )
}

function Get-BrowserLaunchArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    return @($Url)
}


function Get-PairingRemoteUrl {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [PSObject]$PairingResponse,

        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $RemoteUrl = [string](Get-OptionalSetting -Target $PairingResponse -PropertyName 'remote_url' -Default '')
    if (-not [string]::IsNullOrWhiteSpace($RemoteUrl)) {
        return $RemoteUrl
    }
    return "https://<PC-LAN-IP>:$Port/remote"
}

function Get-AutostartTaskSpec {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StartScriptPath,

        [string]$TaskName = 'PC TV Box'
    )

    $NormalizedScriptPath = [System.IO.Path]::GetFullPath($StartScriptPath)
    $Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$NormalizedScriptPath`""

    return [PSCustomObject]@{
        TaskName                  = $TaskName
        StartScriptPath           = $NormalizedScriptPath
        Execute                   = 'powershell.exe'
        Argument                  = $Arguments
        Description               = 'Starts the per-user PC TV Box controller after Windows sign-in.'
        TriggerType               = 'AtLogOn'
        StartWhenAvailable        = $true
        ExecutionTimeLimitMinutes = 5
    }
}

function New-AutostartTaskAction {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StartScriptPath
    )

    $Spec = Get-AutostartTaskSpec -StartScriptPath $StartScriptPath
    return New-ScheduledTaskAction -Execute $Spec.Execute -Argument $Spec.Argument
}

function New-AutostartTaskTrigger {
    [CmdletBinding()]
    param()

    return New-ScheduledTaskTrigger -AtLogOn
}

function New-AutostartTaskSettings {
    [CmdletBinding()]
    param(
        [int]$ExecutionTimeLimitMinutes = 5
    )

    return New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes $ExecutionTimeLimitMinutes)
}

function Install-AutostartTask {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StartScriptPath,

        [string]$TaskName = 'PC TV Box'
    )

    $Spec = Get-AutostartTaskSpec -StartScriptPath $StartScriptPath -TaskName $TaskName
    $Action = New-AutostartTaskAction -StartScriptPath $StartScriptPath
    $Trigger = New-AutostartTaskTrigger
    $Settings = New-AutostartTaskSettings -ExecutionTimeLimitMinutes $Spec.ExecutionTimeLimitMinutes

    Register-ScheduledTask -TaskName $Spec.TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description $Spec.Description -Force | Out-Null
}

function Remove-AutostartTask {
    [CmdletBinding()]
    param(
        [string]$TaskName = 'PC TV Box'
    )

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}

Export-ModuleMember -Function @(
    'Get-OptionalSetting',
    'Get-StartupSettings',
    'Resolve-EdgeExecutable',
    'Get-EdgeUserDataDirectory',
    'Get-EdgeKioskArguments',
    'Get-BrowserLaunchArguments',
    'Get-PairingRemoteUrl',
    'Get-AutostartTaskSpec',
    'New-AutostartTaskAction',
    'New-AutostartTaskTrigger',
    'New-AutostartTaskSettings',
    'Install-AutostartTask',
    'Remove-AutostartTask'
)
