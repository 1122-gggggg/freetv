[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$NoTunnel,
    [switch]$Supervise,
    [switch]$AllowLoopbackOnlyTlsForTesting
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'TVBox.Startup.psm1') -Force

if ($AllowLoopbackOnlyTlsForTesting -and $env:GITHUB_ACTIONS -ne 'true') {
    throw '-AllowLoopbackOnlyTlsForTesting is reserved for isolated GitHub Actions smoke tests.'
}

$Root = Split-Path -Parent $PSScriptRoot

function Assert-NativeSuccess {
    param([string]$Action)

    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

function Get-Listener {
    param([int]$Port)

    return Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Get-ManagedControllerProcess {
    param(
        [int]$ProcessId,
        [string]$PythonPath,
        [string]$BasePythonPath,
        [int]$Port
    )

    $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $Process -or [string]::IsNullOrWhiteSpace($Process.CommandLine)) {
        return $null
    }
    $ParentProcess = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $($Process.ParentProcessId)" `
        -ErrorAction SilentlyContinue
    if (-not (Test-ControllerProcessTreeOwnership `
        -Process $Process `
        -ParentProcess $ParentProcess `
        -PythonPath $PythonPath `
        -BasePythonPath $BasePythonPath `
        -Port $Port)) {
        return $null
    }
    return $Process
}

function Test-ManagedControllerUsesCurrentCertificate {
    param(
        [object]$Process,
        [string]$CertificatePath
    )

    try {
        if ($null -eq $Process.CreationDate) {
            return $false
        }
        $CertificateLastWrite = (Get-Item -LiteralPath $CertificatePath).LastWriteTimeUtc
        return Test-ControllerCertificateFreshness `
            -ProcessCreationDate $Process.CreationDate `
            -CertificateLastWriteTimeUtc $CertificateLastWrite
    } catch {
        return $false
    }
}

function Stop-ManagedController {
    param(
        [int]$ProcessId,
        [int]$Port
    )

    Stop-Process -Id $ProcessId -ErrorAction Stop
    $Deadline = (Get-Date).AddSeconds(10)
    do {
        $RemainingListeners = @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Where-Object { $_.OwningProcess -eq $ProcessId }
        )
        if ($RemainingListeners.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $Deadline)
    throw "Existing PC TV Controller process $ProcessId did not release port $Port."
}

function Stop-RepoCloudflareTunnel {
    param(
        [string]$TunnelUrl,
        [string]$TunnelLog,
        [string]$TunnelOut
    )

    try {
        $Processes = @(Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue)
    } catch {
        return
    }

    $Markers = @($TunnelUrl, $TunnelLog, $TunnelOut) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    foreach ($Process in $Processes) {
        $CommandLine = [string]$Process.CommandLine
        if ([string]::IsNullOrWhiteSpace($CommandLine)) {
            continue
        }
        foreach ($Marker in $Markers) {
            if ($CommandLine.IndexOf($Marker, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                Stop-Process -Id $Process.ProcessId -Force -ErrorAction SilentlyContinue
                break
            }
        }
    }
}



$Python = Join-Path $Root '.venv\Scripts\python.exe'
$FrontendIndex = Join-Path $Root 'frontend\dist\index.html'
$SettingsPath = Join-Path $Root 'config\settings.json'
$SettingsSource = if (Test-Path $SettingsPath) { $SettingsPath } else { Join-Path $Root 'config\settings.example.json' }
try {
    $RawSettings = Get-Content -Raw -Path $SettingsSource | ConvertFrom-Json
    $StartupConfig = Get-StartupSettings -Settings $RawSettings
    $Port = $StartupConfig.Port
    $BindHost = $StartupConfig.BindHost
    $HealthHost = $StartupConfig.HealthHost
    $ConfiguredChromePath = $StartupConfig.ConfiguredChromePath
    $Transport = $StartupConfig.Transport
    $Scheme = $Transport
} catch {
    throw "Could not read server settings from $SettingsSource. $_"
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or -not (Test-VirtualEnvironmentPip -PythonPath $Python)) {
    Write-Host 'This computer is missing a usable TV Box environment. Running setup...'
    & (Join-Path $PSScriptRoot 'setup.ps1')
    Assert-NativeSuccess 'Automatic appliance setup'
}
if (-not (Test-Path $Python)) { throw 'Python virtual environment was not found. Run .\scripts\setup.ps1 first.' }
$BasePython = Resolve-PythonBaseExecutable -PythonPath $Python
if (-not (Test-Path $FrontendIndex)) {
    Write-Host 'Frontend build was not found; building it now...'
    Push-Location (Join-Path $Root 'frontend')
    try {
        & npm run build
        Assert-NativeSuccess 'Building frontend'
    } finally {
        Pop-Location
    }
}
if (-not (Test-Path $FrontendIndex)) { throw 'Frontend build did not produce frontend\dist\index.html.' }
$BackendDirectory = Join-Path $Root 'backend'
$Tls = $null
if ($Transport -eq 'https') {
    $TlsDirectory = Join-Path $Root 'config\tls'
    $TlsOutput = $null
    Push-Location $BackendDirectory
    try {
        $TlsArguments = @('-m', 'app.security.tls', '--directory', $TlsDirectory)
        if ($AllowLoopbackOnlyTlsForTesting) {
            Write-Warning 'GitHub Actions smoke is issuing loopback-only TLS material.'
        } else {
            $TlsArguments += @('--wait-for-lan-seconds', '30')
        }
        $TlsOutput = & $Python @TlsArguments
        Assert-NativeSuccess 'Creating local TLS materials'
    } finally {
        Pop-Location
    }
    try {
        $Tls = (($TlsOutput -join "`n") | ConvertFrom-Json)
    } catch {
        throw 'Could not read locally generated TLS material metadata.'
    }
    if (-not (Test-Path $Tls.certificate) -or -not (Test-Path $Tls.private_key) -or -not (Test-Path $Tls.ca_certificate)) {
        throw 'Local TLS material generation did not produce the expected certificate files.'
    }
}


$Listener = Get-Listener -Port $Port
if ($null -ne $Listener) {
    $ExistingController = Get-ManagedControllerProcess `
        -ProcessId $Listener.OwningProcess `
        -PythonPath $Python `
        -BasePythonPath $BasePython `
        -Port $Port
    if ($null -eq $ExistingController) {
        throw "Configured server port $Port is already in use by a process that is not this PC TV Controller."
    }

    $TransportMatches = Test-ControllerCommandLineTransport `
        -CommandLine $ExistingController.CommandLine `
        -Transport $Transport `
        -CertificatePath $(if ($null -ne $Tls) { [string]$Tls.certificate } else { '' }) `
        -PrivateKeyPath $(if ($null -ne $Tls) { [string]$Tls.private_key } else { '' })
    $CertificateIsCurrent = (
        $Transport -ne 'https' -or
        (Test-ManagedControllerUsesCurrentCertificate -Process $ExistingController -CertificatePath $Tls.certificate)
    )

    if (-not $TransportMatches -or -not $CertificateIsCurrent) {
        if (-not $TransportMatches) {
            Write-Host "Restarting PC TV Controller to apply the configured $($Transport.ToUpperInvariant()) transport and TLS paths..."
        } else {
            Write-Host 'Restarting PC TV Controller to load current TLS material...'
        }
        Stop-ManagedController -ProcessId $Listener.OwningProcess -Port $Port
        $Listener = Get-Listener -Port $Port
        if ($null -ne $Listener) {
            throw "Configured server port $Port remained in use after stopping the previous PC TV Controller."
        }
    } elseif ($Transport -eq 'https') {
        Write-Host "Using existing PC TV Controller with current HTTPS TLS material on port $Port."
    } else {
        Write-Host "Using existing HTTP PC TV Controller on port $Port."
    }
}
if ($null -eq $Listener) {
    Write-Host 'Starting PC TV Controller...'
    $BackendDirectoryArgument = '"{0}"' -f $BackendDirectory
    $UvicornArguments = @(
        '-m', 'uvicorn', 'app.main:app', '--host', $BindHost, '--port', $Port,
        '--app-dir', $BackendDirectoryArgument,
        '--ws', 'websockets-sansio',
        '--limit-concurrency', '64', '--backlog', '64',
        '--ws-max-size', '65536', '--ws-max-queue', '16', '--timeout-keep-alive', '10'
    )
    if ($Transport -eq 'https') {
        $TlsPrivateKeyArgument = '"{0}"' -f ([string]$Tls.private_key)
        $TlsCertificateArgument = '"{0}"' -f ([string]$Tls.certificate)
        $UvicornArguments += @('--ssl-keyfile', $TlsPrivateKeyArgument, '--ssl-certfile', $TlsCertificateArgument)
    }
    $Process = Start-Process -FilePath $Python -WorkingDirectory $BackendDirectory -ArgumentList $UvicornArguments -PassThru
    Write-Host "Backend process started: $($Process.Id)"
}

$HealthUrl = "${Scheme}://${HealthHost}:$Port/api/health"
$PairingUrl = "${Scheme}://${HealthHost}:$Port/api/pairing"
$HealthRequestParameters = @{
    Uri        = $HealthUrl
    TimeoutSec = 2
}
$PairingRequestParameters = @{
    Uri        = $PairingUrl
    TimeoutSec = 15
}
if (
    $Transport -eq 'https' -and
    (Get-Command Invoke-RestMethod).Parameters.ContainsKey('SkipCertificateCheck')
) {
    # PowerShell 7 uses HttpClient and ignores the Windows PowerShell 5.1
    # ServicePointManager callback below. Its native switch is scoped to these
    # loopback readiness requests and does not weaken Remote TLS validation.
    $HealthRequestParameters.SkipCertificateCheck = $true
    $PairingRequestParameters.SkipCertificateCheck = $true
}
$Deadline = (Get-Date).AddSeconds(30)
$Health = $null
$PairingInfo = $null
if ($Transport -eq 'https') {
    $ValidatorTypeName = 'PcTvBox.LocalHealthCertificateValidator'
    if ($null -eq ($ValidatorTypeName -as [type])) {
        Add-Type -TypeDefinition @'
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;

namespace PcTvBox
{
    public static class LocalHealthCertificateValidator
    {
        public static bool Accept(
            object sender,
            X509Certificate certificate,
            X509Chain chain,
            SslPolicyErrors errors)
        {
            return true;
        }
    }
}
'@
    }
    $HealthCallbackType = [System.Net.Security.RemoteCertificateValidationCallback]
    $HealthCallbackMethod = [PcTvBox.LocalHealthCertificateValidator].GetMethod('Accept')
    $LocalHealthCertificateValidationCallback = [System.Delegate]::CreateDelegate(
        $HealthCallbackType,
        $HealthCallbackMethod
    )
    $PreviousCertificateValidationCallback = [System.Net.ServicePointManager]::ServerCertificateValidationCallback
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $LocalHealthCertificateValidationCallback
    try {
        do {
            try {
                $Health = Invoke-RestMethod @HealthRequestParameters
                if ($Health.status -eq 'ok') { break }
            } catch {
                Start-Sleep -Milliseconds 250
            }
        } while ((Get-Date) -lt $Deadline)
        if ($Health -and $Health.status -eq 'ok') {
            $PairingInfo = Invoke-RestMethod @PairingRequestParameters
        }
    } finally {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $PreviousCertificateValidationCallback
    }
} else {
    do {
        try {
            $Health = Invoke-RestMethod @HealthRequestParameters
            if ($Health.status -eq 'ok') { break }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    } while ((Get-Date) -lt $Deadline)
    if ($Health -and $Health.status -eq 'ok') {
        $PairingInfo = Invoke-RestMethod @PairingRequestParameters
    }
}

if (-not $Health -or $Health.status -ne 'ok' -or $Health.backend -ne $true -or $Health.frontend -ne $true) {
    throw "Controller did not become fully healthy at $HealthUrl."
}
if ($null -eq $PairingInfo) {
    throw "Controller did not provide pairing details at $PairingUrl."
}

$TunnelOriginFile = Join-Path $Root 'config\tunnel-origin.txt'
if (-not $NoTunnel) {
    $Cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $Cloudflared) {
        Write-Warning 'cloudflared was not found. Off-LAN Remote stays unavailable. Install with: winget install Cloudflare.cloudflared'
    } else {
        $TunnelLog = Join-Path $Root 'config\cloudflared.log'
        $TunnelOut = Join-Path $Root 'config\cloudflared.out.log'
        New-Item -ItemType Directory -Force -Path (Join-Path $Root 'config') | Out-Null
        Stop-RepoCloudflareTunnel -TunnelUrl "http://${HealthHost}:$Port" -TunnelLog $TunnelLog -TunnelOut $TunnelOut
        if (Test-Path $TunnelLog) { Remove-Item -LiteralPath $TunnelLog -Force -ErrorAction SilentlyContinue }
        if (Test-Path $TunnelOut) { Remove-Item -LiteralPath $TunnelOut -Force -ErrorAction SilentlyContinue }
        Start-Process -FilePath $Cloudflared.Source -ArgumentList @('tunnel', '--url', "http://${HealthHost}:$Port") -RedirectStandardOutput $TunnelOut -RedirectStandardError $TunnelLog -WindowStyle Hidden | Out-Null
        $TunnelDeadline = (Get-Date).AddSeconds(30)
        $PublicOrigin = $null
        do {
            if ((Test-Path $TunnelLog) -or (Test-Path $TunnelOut)) {
                $LogText = ''
                if (Test-Path $TunnelLog) { $LogText += Get-Content -Raw -Path $TunnelLog -ErrorAction SilentlyContinue }
                if (Test-Path $TunnelOut) { $LogText += Get-Content -Raw -Path $TunnelOut -ErrorAction SilentlyContinue }
                if ($LogText -match 'https://(?!api\.)[A-Za-z0-9.-]+\.trycloudflare\.com') {
                    $PublicOrigin = $Matches[0].TrimEnd('/')
                    break
                }
            }
            Start-Sleep -Milliseconds 400
        } while ((Get-Date) -lt $TunnelDeadline)
        if ($PublicOrigin) {
            [System.IO.File]::WriteAllText($TunnelOriginFile, $PublicOrigin)
            $env:PC_TV_PUBLIC_ORIGIN = $PublicOrigin
            $PairingInfo = Invoke-RestMethod -Uri $PairingUrl -TimeoutSec 15
            Write-Host "Cloudflare Tunnel: $PublicOrigin"
        } else {
            Write-Warning 'cloudflared did not print a trycloudflare.com URL in 30s. Phone Remote stays on the LAN URL.'
        }
    }
}

$RemoteUrl = Get-PairingRemoteUrl -PairingResponse $PairingInfo -Port $Port -Scheme $Scheme

$LocalUrl = "${Scheme}://${HealthHost}:$Port/tv"
Write-Host "TV Launcher: $LocalUrl"
Write-Host "Phone Remote: $RemoteUrl"
Write-Host "Health: $HealthUrl"
if ($Transport -eq 'https') {
    Write-Host "Local TLS CA: $($Tls.ca_certificate)"
    Write-Host "CA SHA-256: $($Tls.ca_sha256)"
    Write-Warning 'Install and trust this local CA on each phone before opening the HTTPS Remote; see docs\WINDOWS_SETUP.md.'
} elseif ($RemoteUrl -like 'https://*.trycloudflare.com/*') {
    Write-Host 'Transport: HTTP locally; phone uses the Cloudflare HTTPS URL. Rescan the QR after each restart.'
} else {
    Write-Host "Transport: HTTP (private LAN only). Install cloudflared for off-LAN Remote."
}

if (-not $NoBrowser) {
    $Chrome = Resolve-ChromeExecutable -ConfiguredPath $ConfiguredChromePath
    if ($Chrome) {
        $KioskUserDataDir = Get-LauncherUserDataDirectory -RootDirectory $Root
        $KioskArguments = Get-ChromeLauncherKioskArguments -Url $LocalUrl -UserDataDir $KioskUserDataDir
        Start-Process -FilePath $Chrome -ArgumentList $KioskArguments
    } else {
        Write-Warning 'Google Chrome was not found; opening the TV Launcher with the default browser instead of kiosk mode.'
        Start-Process $LocalUrl
    }
}

if ($Supervise) {
    $SupervisedListener = Get-Listener -Port $Port
    if ($null -eq $SupervisedListener) {
        throw "Cannot supervise the PC TV Controller because port $Port has no listener."
    }
    $SupervisedProcess = Get-ManagedControllerProcess `
        -ProcessId $SupervisedListener.OwningProcess `
        -PythonPath $Python `
        -BasePythonPath $BasePython `
        -Port $Port
    if ($null -eq $SupervisedProcess) {
        throw 'Cannot supervise a controller process that is not owned by this checkout.'
    }
    Write-Host "Supervising PC TV Controller process $($SupervisedProcess.ProcessId)."
    Wait-Process -Id $SupervisedProcess.ProcessId -ErrorAction SilentlyContinue
    throw "PC TV Controller process $($SupervisedProcess.ProcessId) exited unexpectedly."
}
