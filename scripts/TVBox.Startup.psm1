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

    $Transport = [string](Get-OptionalSetting -Target $Server -PropertyName 'transport' -Default 'http')
    if ($Transport -notin @('http', 'https')) {
        throw "Configured server transport must be 'http' or 'https'."
    }

    $Applications = Get-OptionalSetting -Target $Settings -PropertyName 'applications'
    $ConfiguredEdgePath = ''
    if ($null -ne $Applications) {
        $ConfiguredEdgePath = [string](Get-OptionalSetting -Target $Applications -PropertyName 'edge_path' -Default '')
    }

    return [PSCustomObject]@{
        Port               = $Port
        BindHost           = $BindHost
        HealthHost         = $HealthHost
        Transport          = $Transport
        ConfiguredEdgePath = $ConfiguredEdgePath
    }
}

function ConvertFrom-ControllerCommandLine {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [string]$CommandLine
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return @()
    }

    return @(
        [regex]::Matches($CommandLine, '(?:[^\s"]+|"[^"]*")+') | ForEach-Object {
            $_.Value.Replace('"', '')
        }
    )
}

function Test-CommandLineOptionValue {
    [CmdletBinding()]
    param(
        [string[]]$Tokens,
        [string]$Name,
        [string]$ExpectedValue,
        [switch]$PathValue
    )

    $Matches = @()
    for ($Index = 0; $Index -lt $Tokens.Count; $Index++) {
        $Token = $Tokens[$Index]
        if ($Token -ieq $Name) {
            $HasValue = ($Index + 1) -lt $Tokens.Count
            $Matches += [PSCustomObject]@{
                HasValue = $HasValue
                Value    = $(if ($HasValue) { $Tokens[$Index + 1] } else { '' })
            }
        } elseif ($Token.StartsWith("$Name=", [System.StringComparison]::OrdinalIgnoreCase)) {
            $Matches += [PSCustomObject]@{
                HasValue = $true
                Value    = $Token.Substring($Name.Length + 1)
            }
        }
    }

    if ($Matches.Count -ne 1 -or -not $Matches[0].HasValue) {
        return $false
    }
    if (-not $PathValue) {
        return $Matches[0].Value -ieq $ExpectedValue
    }

    try {
        if (
            -not [System.IO.Path]::IsPathRooted([string]$Matches[0].Value) -or
            -not [System.IO.Path]::IsPathRooted($ExpectedValue)
        ) {
            return $false
        }
        $ActualPath = [System.IO.Path]::GetFullPath([string]$Matches[0].Value)
        $ExpectedPath = [System.IO.Path]::GetFullPath($ExpectedValue)
        return [string]::Equals($ActualPath, $ExpectedPath, [System.StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Test-CommandLineOptionAbsent {
    [CmdletBinding()]
    param(
        [string[]]$Tokens,
        [string]$Name
    )

    foreach ($Token in $Tokens) {
        if (
            $Token -ieq $Name -or
            $Token.StartsWith("$Name=", [System.StringComparison]::OrdinalIgnoreCase)
        ) {
            return $false
        }
    }
    return $true
}

function Test-ControllerCommandLineOwnership {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [string]$CommandLine,

        [Parameter(Mandatory = $true)]
        [string]$PythonPath,

        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $Tokens = @(ConvertFrom-ControllerCommandLine -CommandLine $CommandLine)
    if ($Tokens.Count -lt 4) {
        return $false
    }

    try {
        if (
            -not [System.IO.Path]::IsPathRooted($Tokens[0]) -or
            -not [System.IO.Path]::IsPathRooted($PythonPath)
        ) {
            return $false
        }
        $ActualPythonPath = [System.IO.Path]::GetFullPath($Tokens[0])
        $ExpectedPythonPath = [System.IO.Path]::GetFullPath($PythonPath)
    } catch {
        return $false
    }
    if (-not [string]::Equals($ActualPythonPath, $ExpectedPythonPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    if ($Tokens[1] -ine '-m' -or $Tokens[2] -ine 'uvicorn' -or $Tokens[3] -ine 'app.main:app') {
        return $false
    }
    foreach ($Token in $Tokens) {
        if (
            $Token -ieq '--reload' -or
            $Token.StartsWith('--reload=', [System.StringComparison]::OrdinalIgnoreCase) -or
            $Token -ieq '--workers' -or
            $Token.StartsWith('--workers=', [System.StringComparison]::OrdinalIgnoreCase)
        ) {
            return $false
        }
    }

    $ExpectedProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $ExpectedPythonPath))
    $ExpectedAppDirectory = Join-Path $ExpectedProjectRoot 'backend'
    $AppDirectoryMatches = (
        (Test-CommandLineOptionAbsent -Tokens $Tokens -Name '--app-dir') -or
        (Test-CommandLineOptionValue -Tokens $Tokens -Name '--app-dir' -ExpectedValue $ExpectedAppDirectory -PathValue)
    )

    return (
        (Test-CommandLineOptionValue -Tokens $Tokens -Name '--host' -ExpectedValue '0.0.0.0') -and
        (Test-CommandLineOptionValue -Tokens $Tokens -Name '--port' -ExpectedValue ([string]$Port)) -and
        $AppDirectoryMatches
    )
}

function Test-ControllerProcessOwnership {
    [CmdletBinding()]
    param(
        [PSObject]$Process,

        [Parameter(Mandatory = $true)]
        [string]$PythonPath,

        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    if ($null -eq $Process) {
        return $false
    }
    $ExecutablePath = [string](Get-OptionalSetting -Target $Process -PropertyName 'ExecutablePath' -Default '')
    $CommandLine = [string](Get-OptionalSetting -Target $Process -PropertyName 'CommandLine' -Default '')
    if ([string]::IsNullOrWhiteSpace($ExecutablePath) -or [string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }
    try {
        $ActualExecutablePath = [System.IO.Path]::GetFullPath($ExecutablePath)
        $ExpectedPythonPath = [System.IO.Path]::GetFullPath($PythonPath)
    } catch {
        return $false
    }
    if (-not [string]::Equals($ActualExecutablePath, $ExpectedPythonPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    return Test-ControllerCommandLineOwnership -CommandLine $CommandLine -PythonPath $PythonPath -Port $Port
}

function Test-ControllerProcessTreeOwnership {
    [CmdletBinding()]
    param(
        [PSObject]$Process,

        [PSObject]$ParentProcess,

        [Parameter(Mandatory = $true)]
        [string]$PythonPath,

        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    if (Test-ControllerProcessOwnership -Process $Process -PythonPath $PythonPath -Port $Port) {
        return $true
    }
    if ($null -eq $Process -or $null -eq $ParentProcess) {
        return $false
    }

    $ParentProcessId = Get-OptionalSetting -Target $Process -PropertyName 'ParentProcessId'
    $ActualParentProcessId = Get-OptionalSetting -Target $ParentProcess -PropertyName 'ProcessId'
    $CommandLine = [string](Get-OptionalSetting -Target $Process -PropertyName 'CommandLine' -Default '')
    if (
        $null -eq $ParentProcessId -or
        $null -eq $ActualParentProcessId -or
        [int]$ParentProcessId -ne [int]$ActualParentProcessId -or
        -not (Test-ControllerProcessOwnership -Process $ParentProcess -PythonPath $PythonPath -Port $Port)
    ) {
        return $false
    }

    return Test-ControllerCommandLineOwnership -CommandLine $CommandLine -PythonPath $PythonPath -Port $Port
}

function Test-ControllerCommandLineTransport {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [string]$CommandLine,

        [ValidateSet('http', 'https')]
        [string]$Transport,

        [string]$CertificatePath = '',
        [string]$PrivateKeyPath = ''
    )

    $Tokens = @(ConvertFrom-ControllerCommandLine -CommandLine $CommandLine)
    if ($Transport -eq 'http') {
        return (
            (Test-CommandLineOptionAbsent -Tokens $Tokens -Name '--ssl-certfile') -and
            (Test-CommandLineOptionAbsent -Tokens $Tokens -Name '--ssl-keyfile')
        )
    }
    if ([string]::IsNullOrWhiteSpace($CertificatePath) -or [string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
        return $false
    }

    return (
        (Test-CommandLineOptionValue -Tokens $Tokens -Name '--ssl-certfile' -ExpectedValue $CertificatePath -PathValue) -and
        (Test-CommandLineOptionValue -Tokens $Tokens -Name '--ssl-keyfile' -ExpectedValue $PrivateKeyPath -PathValue)
    )
}

function Test-ControllerCertificateFreshness {
    [CmdletBinding()]
    param(
        $ProcessCreationDate,
        $CertificateLastWriteTimeUtc
    )

    if ($null -eq $ProcessCreationDate -or $null -eq $CertificateLastWriteTimeUtc) {
        return $false
    }
    try {
        $StartedAtUtc = ([datetime]$ProcessCreationDate).ToUniversalTime()
        $CertificateTimeUtc = ([datetime]$CertificateLastWriteTimeUtc).ToUniversalTime()
        return $StartedAtUtc -ge $CertificateTimeUtc
    } catch {
        return $false
    }
}

function Test-PythonRuntimeVersion {
    [CmdletBinding()]
    param(
        $VersionValue,
        [version]$MinimumVersion = [version]'3.11'
    )

    if ($null -eq $VersionValue) {
        return $false
    }
    try {
        return ([version]$VersionValue) -ge $MinimumVersion
    } catch {
        return $false
    }
}

function Test-PythonVirtualEnvironmentRuntime {
    [CmdletBinding()]
    param(
        [PSObject]$Runtime,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedDirectory,

        [version]$MinimumVersion = [version]'3.11'
    )

    if ($null -eq $Runtime) {
        return $false
    }
    $VersionValue = Get-OptionalSetting -Target $Runtime -PropertyName 'Version'
    $Prefix = [string](Get-OptionalSetting -Target $Runtime -PropertyName 'Prefix' -Default '')
    $BasePrefix = [string](Get-OptionalSetting -Target $Runtime -PropertyName 'BasePrefix' -Default '')
    if (
        -not (Test-PythonRuntimeVersion -VersionValue $VersionValue -MinimumVersion $MinimumVersion) -or
        [string]::IsNullOrWhiteSpace($Prefix) -or
        [string]::IsNullOrWhiteSpace($BasePrefix)
    ) {
        return $false
    }

    try {
        $ExpectedPath = [System.IO.Path]::GetFullPath($ExpectedDirectory)
        $PrefixPath = [System.IO.Path]::GetFullPath($Prefix)
        $BasePrefixPath = [System.IO.Path]::GetFullPath($BasePrefix)
    } catch {
        return $false
    }
    return (
        [string]::Equals($PrefixPath, $ExpectedPath, [System.StringComparison]::OrdinalIgnoreCase) -and
        -not [string]::Equals($PrefixPath, $BasePrefixPath, [System.StringComparison]::OrdinalIgnoreCase)
    )
}

function Select-PythonRuntimeCandidate {
    [CmdletBinding()]
    param(
        [object[]]$Candidates,
        [version]$MinimumVersion = [version]'3.11'
    )

    foreach ($Candidate in @($Candidates)) {
        if ($null -eq $Candidate) {
            continue
        }
        $Executable = [string](Get-OptionalSetting -Target $Candidate -PropertyName 'Executable' -Default '')
        $VersionValue = Get-OptionalSetting -Target $Candidate -PropertyName 'Version'
        if ([string]::IsNullOrWhiteSpace($Executable) -or $null -eq $VersionValue) {
            continue
        }
        if (Test-PythonRuntimeVersion -VersionValue $VersionValue -MinimumVersion $MinimumVersion) {
            return $Candidate
        }
    }
    return $null
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
        '--disable-extensions',
        '--disable-sync',
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
        [int]$Port,

        [string]$Scheme = 'http'
    )

    $RemoteUrl = [string](Get-OptionalSetting -Target $PairingResponse -PropertyName 'remote_url' -Default '')
    if (-not [string]::IsNullOrWhiteSpace($RemoteUrl)) {
        return $RemoteUrl
    }
    return "${Scheme}://<PC-LAN-IP>:$Port/remote"
}

function Get-AutostartTaskSpec {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StartScriptPath,

        [string]$TaskName = 'PC TV Box',

        [string]$UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    )

    $NormalizedScriptPath = [System.IO.Path]::GetFullPath($StartScriptPath)
    $Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$NormalizedScriptPath`" -Supervise"

    return [PSCustomObject]@{
        TaskName                  = $TaskName
        StartScriptPath           = $NormalizedScriptPath
        Execute                   = 'powershell.exe'
        Argument                  = $Arguments
        Description               = 'Starts and supervises the per-user PC TV Box controller after Windows sign-in.'
        UserId                    = $UserId
        TriggerType               = 'AtLogOn'
        StartWhenAvailable        = $true
        AllowStartIfOnBatteries   = $true
        DontStopIfGoingOnBatteries = $true
        ExecutionTimeLimitMinutes = 0
        RestartCount              = 3
        RestartIntervalMinutes    = 1
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
    param(
        [string]$UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    )

    return New-ScheduledTaskTrigger -AtLogOn -User $UserId
}

function New-AutostartTaskSettings {
    [CmdletBinding()]
    param(
        [ValidateRange(0, 1440)]
        [int]$ExecutionTimeLimitMinutes = 0,

        [ValidateRange(1, 999)]
        [int]$RestartCount = 3,

        [ValidateRange(1, 1440)]
        [int]$RestartIntervalMinutes = 1
    )

    return New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $ExecutionTimeLimitMinutes) `
        -RestartCount $RestartCount `
        -RestartInterval (New-TimeSpan -Minutes $RestartIntervalMinutes)
}

function Test-AutostartTaskOwnership {
    [CmdletBinding()]
    param(
        [PSObject]$Task,

        [Parameter(Mandatory = $true)]
        [string]$StartScriptPath
    )

    if ($null -eq $Task) {
        return $false
    }
    $Actions = @(Get-OptionalSetting -Target $Task -PropertyName 'Actions' -Default @())
    if ($Actions.Count -ne 1) {
        return $false
    }
    $Execute = [string](Get-OptionalSetting -Target $Actions[0] -PropertyName 'Execute' -Default '')
    if ([System.IO.Path]::GetFileName($Execute) -ine 'powershell.exe') {
        return $false
    }
    $Arguments = [string](Get-OptionalSetting -Target $Actions[0] -PropertyName 'Arguments' -Default '')
    $Spec = Get-AutostartTaskSpec -StartScriptPath $StartScriptPath
    $LegacyArguments = $Spec.Argument.Substring(0, $Spec.Argument.Length - ' -Supervise'.Length)
    return $Arguments -ieq $Spec.Argument -or $Arguments -ieq $LegacyArguments
}

function Install-AutostartTask {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StartScriptPath,

        [string]$TaskName = 'PC TV Box'
    )

    $Spec = Get-AutostartTaskSpec -StartScriptPath $StartScriptPath -TaskName $TaskName
    $ExistingTasks = @(Get-ScheduledTask -TaskName $Spec.TaskName -ErrorAction SilentlyContinue)
    if ($ExistingTasks.Count -gt 1) {
        throw "Refusing to overwrite multiple scheduled tasks named '$($Spec.TaskName)'."
    }
    if (
        $ExistingTasks.Count -eq 1 -and
        -not (Test-AutostartTaskOwnership -Task $ExistingTasks[0] -StartScriptPath $StartScriptPath)
    ) {
        throw "Refusing to overwrite scheduled task '$($Spec.TaskName)' because it is not owned by this checkout."
    }
    $Action = New-AutostartTaskAction -StartScriptPath $StartScriptPath
    $Trigger = New-AutostartTaskTrigger -UserId $Spec.UserId
    $Settings = New-AutostartTaskSettings `
        -ExecutionTimeLimitMinutes $Spec.ExecutionTimeLimitMinutes `
        -RestartCount $Spec.RestartCount `
        -RestartIntervalMinutes $Spec.RestartIntervalMinutes

    Register-ScheduledTask -TaskName $Spec.TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description $Spec.Description -Force | Out-Null
}

function Remove-AutostartTask {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StartScriptPath,

        [string]$TaskName = 'PC TV Box'
    )

    $ExistingTasks = @(Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
    if ($ExistingTasks.Count -eq 0) {
        return
    }
    if ($ExistingTasks.Count -gt 1) {
        throw "Refusing to remove multiple scheduled tasks named '$TaskName'."
    }
    if (-not (Test-AutostartTaskOwnership -Task $ExistingTasks[0] -StartScriptPath $StartScriptPath)) {
        throw "Refusing to remove scheduled task '$TaskName' because it is not owned by this checkout."
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
}

Export-ModuleMember -Function @(
    'Get-OptionalSetting',
    'Get-StartupSettings',
    'Test-ControllerCommandLineOwnership',
    'Test-ControllerProcessOwnership',
    'Test-ControllerProcessTreeOwnership',
    'Test-ControllerCommandLineTransport',
    'Test-ControllerCertificateFreshness',
    'Test-PythonRuntimeVersion',
    'Test-PythonVirtualEnvironmentRuntime',
    'Select-PythonRuntimeCandidate',
    'Resolve-EdgeExecutable',
    'Get-EdgeUserDataDirectory',
    'Get-EdgeKioskArguments',
    'Get-BrowserLaunchArguments',
    'Get-PairingRemoteUrl',
    'Get-AutostartTaskSpec',
    'New-AutostartTaskAction',
    'New-AutostartTaskTrigger',
    'New-AutostartTaskSettings',
    'Test-AutostartTaskOwnership',
    'Install-AutostartTask',
    'Remove-AutostartTask'
)
