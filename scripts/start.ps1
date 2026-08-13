[CmdletBinding()]
param(
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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
        [string]$CertificatePath,
        [int]$Port
    )

    $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $Process -or [string]::IsNullOrWhiteSpace($Process.CommandLine)) {
        return $null
    }
    $PythonPattern = [regex]::Escape((Resolve-Path -LiteralPath $PythonPath).Path)
    $CertificatePattern = [regex]::Escape((Resolve-Path -LiteralPath $CertificatePath).Path)
    $PortPattern = [regex]::Escape([string]$Port)
    $CertificateParameterPattern = '(?i)--ssl-certfile\s+"?' + $CertificatePattern + '"?(?:\s|$)'
    if (
        $Process.CommandLine -notmatch "(?i)$PythonPattern" -or
        $Process.CommandLine -notmatch '(?i)(?:^|\s)-m\s+uvicorn\s+app\.main:app(?:\s|$)' -or
        $Process.CommandLine -notmatch "(?i)--port\s+$PortPattern(?:\s|$)" -or
        $Process.CommandLine -notmatch $CertificateParameterPattern
    ) {
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
        $ControllerStartedAt = $Process.CreationDate.ToUniversalTime()
        $CertificateLastWrite = (Get-Item -LiteralPath $CertificatePath).LastWriteTimeUtc
        return $ControllerStartedAt -ge $CertificateLastWrite
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

$Python = Join-Path $Root '.venv\Scripts\python.exe'
$FrontendIndex = Join-Path $Root 'frontend\dist\index.html'
$SettingsPath = Join-Path $Root 'config\settings.json'
$SettingsSource = if (Test-Path $SettingsPath) { $SettingsPath } else { Join-Path $Root 'config\settings.example.json' }
try {
    $ServerSettings = (Get-Content -Raw -Path $SettingsSource | ConvertFrom-Json).server
    $Port = [int]$ServerSettings.port
    $BindHost = [string]$ServerSettings.host
} catch {
    throw "Could not read server settings from $SettingsSource."
}
if ($Port -lt 1 -or $Port -gt 65535) { throw "Configured server port is invalid: $Port" }
if ([string]::IsNullOrWhiteSpace($BindHost)) { throw 'Configured server host is required.' }
$HealthHost = if ($BindHost -eq '0.0.0.0') { '127.0.0.1' } else { $BindHost }

if (-not (Test-Path $Python)) { throw 'Python virtual environment was not found. Run .\scripts\setup.ps1 first.' }
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
$TlsDirectory = Join-Path $Root 'config\tls'
$BackendDirectory = Join-Path $Root 'backend'
$TlsOutput = $null
Push-Location $BackendDirectory
try {
    $TlsOutput = & $Python -m app.security.tls --directory $TlsDirectory
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


$Listener = Get-Listener -Port $Port
if ($null -ne $Listener) {
    $ExistingController = Get-ManagedControllerProcess `
        -ProcessId $Listener.OwningProcess `
        -PythonPath $Python `
        -CertificatePath $Tls.certificate `
        -Port $Port
    if ($null -eq $ExistingController) {
        throw "Configured server port $Port is already in use by a process that is not this PC TV Controller."
    }
    if (-not (Test-ManagedControllerUsesCurrentCertificate -Process $ExistingController -CertificatePath $Tls.certificate)) {
        Write-Host 'Restarting PC TV Controller to load current TLS material...'
        Stop-ManagedController -ProcessId $Listener.OwningProcess -Port $Port
        $Listener = Get-Listener -Port $Port
        if ($null -ne $Listener) {
            throw "Configured server port $Port remained in use after stopping the previous PC TV Controller."
        }
    } else {
        Write-Host "Using existing PC TV Controller with current TLS material on port $Port."
    }
}
if ($null -eq $Listener) {
    Write-Host 'Starting PC TV Controller...'
    $TlsPrivateKeyArgument = '"{0}"' -f ([string]$Tls.private_key)
    $TlsCertificateArgument = '"{0}"' -f ([string]$Tls.certificate)
    $UvicornArguments = @(
        '-m', 'uvicorn', 'app.main:app', '--host', $BindHost, '--port', $Port,
        '--ssl-keyfile', $TlsPrivateKeyArgument, '--ssl-certfile', $TlsCertificateArgument,
        '--ws', 'websockets-sansio',
        '--limit-concurrency', '64', '--backlog', '64',
        '--ws-max-size', '65536', '--ws-max-queue', '16', '--timeout-keep-alive', '10'
    )
    $Process = Start-Process -FilePath $Python -WorkingDirectory $BackendDirectory -ArgumentList $UvicornArguments -PassThru
    Write-Host "Backend process started: $($Process.Id)"
}

$HealthUrl = "https://${HealthHost}:$Port/api/health"
$Deadline = (Get-Date).AddSeconds(30)
$Health = $null
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
            $Health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
            if ($Health.status -eq 'ok') { break }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    } while ((Get-Date) -lt $Deadline)
} finally {
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $PreviousCertificateValidationCallback
}

if (-not $Health -or $Health.status -ne 'ok' -or $Health.backend -ne $true -or $Health.frontend -ne $true) {
    throw "Controller did not become fully healthy at $HealthUrl."
}
$DefaultRoute = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric, InterfaceMetric |
    Select-Object -First 1
$LanAddress = if ($DefaultRoute) {
    Get-NetIPAddress -InterfaceIndex $DefaultRoute.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1 -ExpandProperty IPAddress
}
$RemoteUrl = if ($LanAddress) { "https://${LanAddress}:$Port/remote" } else { "https://<PC-LAN-IP>:$Port/remote" }

$LocalUrl = "https://${HealthHost}:$Port/tv"
Write-Host "TV Launcher: $LocalUrl"
Write-Host "Phone Remote: $RemoteUrl"
Write-Host "Health: $HealthUrl"
Write-Host "Local TLS CA: $($Tls.ca_certificate)"
Write-Host "CA SHA-256: $($Tls.ca_sha256)"
Write-Warning 'Install and trust this local CA on each phone before opening the HTTPS Remote; see docs\WINDOWS_SETUP.md.'

if (-not $NoBrowser) {
    Start-Process $LocalUrl
}
