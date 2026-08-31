[CmdletBinding()]
param(
    [string]$PackagePath = '',
    [string]$OutputPath = '',
    [string]$BuildPythonPath = '',
    [string]$SevenZipPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http -ErrorAction Stop

$Root = Split-Path -Parent $PSScriptRoot
$LockPath = Join-Path $Root 'installer\windows-bundle.lock.json'
$RequirementsLockPath = Join-Path $Root 'backend\requirements-windows.lock.txt'
$CommittedLicensesPath = Join-Path $Root 'installer\licenses'

function Assert-AllowedArtifactUri {
    param([Parameter(Mandatory = $true)][uri]$Uri)

    if ($Uri.Scheme -ne 'https') {
        throw "Artifact URL scheme is not approved: $Uri"
    }
    $HostName = $Uri.DnsSafeHost.ToLowerInvariant()
    $AllowedHosts = @(
        'www.python.org',
        'github.com',
        'objects.githubusercontent.com',
        'release-assets.githubusercontent.com'
    )
    if ($HostName -notin $AllowedHosts) {
        throw "Artifact URL host is not approved: $HostName"
    }
}

function Invoke-ArtifactRequest {
    param(
        [Parameter(Mandatory = $true)][uri]$Uri,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $Handler = [System.Net.Http.HttpClientHandler]::new()
    $Handler.AllowAutoRedirect = $false
    $Client = [System.Net.Http.HttpClient]::new($Handler)
    try {
        $Response = $Client.GetAsync(
            $Uri,
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        try {
            $StatusCode = [int]$Response.StatusCode
            $Location = $null
            if ($null -ne $Response.Headers.Location) {
                $Location = [string]$Response.Headers.Location
            }
            if ($StatusCode -in @(301, 302, 303, 307, 308)) {
                return [pscustomobject]@{
                    StatusCode = $StatusCode
                    Location = $Location
                }
            }
            if ($StatusCode -lt 200 -or $StatusCode -gt 299) {
                throw "Artifact request failed with HTTP status $StatusCode for $Uri."
            }

            $OutputStream = [System.IO.File]::Open(
                $Destination,
                [System.IO.FileMode]::Create,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try {
                $null = $Response.Content.CopyToAsync($OutputStream).GetAwaiter().GetResult()
            }
            finally {
                $OutputStream.Dispose()
            }
            return [pscustomobject]@{
                StatusCode = $StatusCode
                Location = $null
            }
        }
        finally {
            $Response.Dispose()
        }
    }
    finally {
        $Client.Dispose()
    }
}

function Get-VerifiedArtifact {
    param(
        [Parameter(Mandatory = $true)][object]$Component,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $CurrentUri = [uri][string]$Component.url
    Assert-AllowedArtifactUri -Uri $CurrentUri

    $DestinationDirectory = Split-Path -Parent $Destination
    if (-not (Test-Path -LiteralPath $DestinationDirectory)) {
        New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
    }
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Force
    }

    $MaximumRedirects = 5
    $RedirectCount = 0
    while ($true) {
        $Result = Invoke-ArtifactRequest -Uri $CurrentUri -Destination $Destination
        if ([int]$Result.StatusCode -notin @(301, 302, 303, 307, 308)) {
            break
        }
        if ($RedirectCount -ge $MaximumRedirects) {
            throw "Artifact redirect limit exceeded for $($Component.url)."
        }
        if ([string]::IsNullOrWhiteSpace([string]$Result.Location)) {
            throw "Artifact redirect is missing a Location header for $CurrentUri."
        }
        try {
            $NextUri = [uri]::new($CurrentUri, [string]$Result.Location)
        }
        catch {
            throw "Artifact redirect Location is invalid for $CurrentUri."
        }
        Assert-AllowedArtifactUri -Uri $NextUri
        $CurrentUri = $NextUri
        $RedirectCount += 1
    }

    $Item = Get-Item -LiteralPath $Destination
    if ($Item.Length -ne [int64]$Component.size) {
        throw "Artifact size mismatch for $($Component.url)."
    }
    $Actual = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne [string]$Component.sha256) {
        throw "Artifact SHA-256 mismatch for $($Component.url)."
    }
}

function Resolve-BuildExecutable {
    param(
        [string]$ConfiguredPath,
        [Parameter(Mandatory = $true)][string[]]$CommandNames,
        [string[]]$CandidatePaths = @(),
        [Parameter(Mandatory = $true)][string]$Description
    )

    if (-not [string]::IsNullOrWhiteSpace($ConfiguredPath)) {
        if (-not (Test-Path -LiteralPath $ConfiguredPath -PathType Leaf)) {
            throw "$Description was not found at $ConfiguredPath."
        }
        return (Resolve-Path -LiteralPath $ConfiguredPath).Path
    }

    foreach ($Candidate in $CandidatePaths) {
        if (-not [string]::IsNullOrWhiteSpace($Candidate) -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }

    foreach ($CommandName in $CommandNames) {
        $Command = Get-Command $CommandName -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $Command) {
            return $Command.Source
        }
    }
    throw "$Description is required."
}

function Copy-PortablePayload {
    param(
        [Parameter(Mandatory = $true)][string]$ExpandedPath,
        [Parameter(Mandatory = $true)][string]$StagePath
    )

    $PortableRoot = Join-Path $ExpandedPath 'pc-tv-box'
    if (-not (Test-Path -LiteralPath $PortableRoot -PathType Container)) {
        throw 'Portable package must contain the pc-tv-box root directory.'
    }
    $UnexpectedEntries = @(Get-ChildItem -LiteralPath $ExpandedPath -Force |
        Where-Object { $_.FullName -ne $PortableRoot })
    if ($UnexpectedEntries.Count -ne 0) {
        throw 'Portable package contains entries outside the pc-tv-box root directory.'
    }

    New-Item -ItemType Directory -Force -Path $StagePath | Out-Null
    foreach ($Entry in Get-ChildItem -LiteralPath $PortableRoot -Force) {
        Copy-Item -LiteralPath $Entry.FullName -Destination $StagePath -Recurse -Force
    }
}

function Invoke-OfflineBundleBuild {
    if ([string]::IsNullOrWhiteSpace($PackagePath)) {
        throw 'PackagePath is required.'
    }
    if ([string]::IsNullOrWhiteSpace($OutputPath)) {
        throw 'OutputPath is required.'
    }
    if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) {
        throw "Portable package was not found at $PackagePath."
    }
    foreach ($RequiredPath in @($LockPath, $RequirementsLockPath)) {
        if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
            throw "Required bundle input is missing: $RequiredPath"
        }
    }

    $ResolvedPackagePath = (Resolve-Path -LiteralPath $PackagePath).Path
    $BuildPythonPath = Resolve-BuildExecutable `
        -ConfiguredPath $BuildPythonPath `
        -CommandNames @('python3.13.exe', 'python3.13', 'python.exe', 'python') `
        -CandidatePaths @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
            (Join-Path $env:ProgramFiles 'Python313\python.exe'),
            'C:\Python313\python.exe'
        ) `
        -Description 'A Python 3.13 build interpreter'
    $SevenZipPath = Resolve-BuildExecutable `
        -ConfiguredPath $SevenZipPath `
        -CommandNames @('7z.exe', '7z') `
        -CandidatePaths @(
            (Join-Path $env:ProgramFiles '7-Zip\7z.exe'),
            (Join-Path ${env:ProgramFiles(x86)} '7-Zip\7z.exe')
        ) `
        -Description '7-Zip'
    $VersionProbe = "import struct, sys; print('{}.{}|{}'.format(sys.version_info.major, sys.version_info.minor, struct.calcsize('P') * 8))"
    $BuildRuntimeOutput = & $BuildPythonPath -c $VersionProbe
    if ($LASTEXITCODE -ne 0) {
        throw 'Querying the build interpreter failed.'
    }
    $BuildRuntime = ([string]$BuildRuntimeOutput).Trim()
    if ($BuildRuntime -ne '3.13|64') {
        throw "The build interpreter must be 64-bit Python 3.13; found $BuildRuntime."
    }
    $FinalOutputPath = [System.IO.Path]::GetFullPath($OutputPath)

    $Lock = Get-Content -Raw -LiteralPath $LockPath | ConvertFrom-Json
    if ([int]$Lock.schema_version -ne 1) {
        throw "Unsupported Windows bundle lock schema: $($Lock.schema_version)"
    }
    foreach ($ComponentName in @('python', 'mpv', 'cloudflared')) {
        $Component = $Lock.$ComponentName
        if ([string]$Component.architecture -ne 'x86_64') {
            throw "Unsupported architecture for ${ComponentName}: $($Component.architecture)"
        }
        if ([string]$Component.sha256 -notmatch '^[0-9a-f]{64}$') {
            throw "Invalid SHA-256 in bundle lock for $ComponentName."
        }
        Assert-AllowedArtifactUri -Uri ([uri][string]$Component.url)
    }

    $TemporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
        'freetv-offline-bundle-' + [guid]::NewGuid().ToString('N')
    )
    $ExpandedPackagePath = Join-Path $TemporaryRoot 'package'
    $OutputPath = Join-Path $TemporaryRoot 'stage'
    $ArtifactPath = Join-Path $TemporaryRoot 'artifacts'
    try {
        New-Item -ItemType Directory -Force -Path $ExpandedPackagePath, $ArtifactPath | Out-Null
        Expand-Archive -LiteralPath $ResolvedPackagePath -DestinationPath $ExpandedPackagePath
        Copy-PortablePayload -ExpandedPath $ExpandedPackagePath -StagePath $OutputPath

        $PythonArchivePath = Join-Path $ArtifactPath 'python-embed.zip'
        $MpvArchivePath = Join-Path $ArtifactPath 'mpv.7z'
        $CloudflaredArtifactPath = Join-Path $ArtifactPath 'cloudflared.exe'
        Get-VerifiedArtifact -Component $Lock.python -Destination $PythonArchivePath
        Get-VerifiedArtifact -Component $Lock.mpv -Destination $MpvArchivePath
        Get-VerifiedArtifact -Component $Lock.cloudflared -Destination $CloudflaredArtifactPath

        $RuntimePath = Join-Path $OutputPath 'runtime'
        $MpvPath = Join-Path $OutputPath 'tools\mpv'
        $CloudflaredPath = Join-Path $OutputPath 'tools\cloudflared'
        $LicensesPath = Join-Path $OutputPath 'licenses'
        New-Item -ItemType Directory -Force -Path @(
            $RuntimePath,
            $MpvPath,
            $CloudflaredPath,
            $LicensesPath
        ) | Out-Null

        Expand-Archive -LiteralPath $PythonArchivePath -DestinationPath $RuntimePath
        & $SevenZipPath x $MpvArchivePath "-o$MpvPath" -y | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Extracting the verified mpv archive failed.'
        }
        Copy-Item -LiteralPath $CloudflaredArtifactPath `
            -Destination (Join-Path $CloudflaredPath 'cloudflared.exe')

        foreach ($RequiredRuntimePath in @(
            (Join-Path $RuntimePath 'python.exe'),
            (Join-Path $RuntimePath 'pythonw.exe'),
            (Join-Path $RuntimePath 'LICENSE.txt'),
            (Join-Path $MpvPath 'mpv.exe'),
            (Join-Path $CloudflaredPath 'cloudflared.exe')
        )) {
            if (-not (Test-Path -LiteralPath $RequiredRuntimePath -PathType Leaf)) {
                throw "Verified bundle component did not produce $RequiredRuntimePath."
            }
        }

        & $BuildPythonPath -m pip install `
            --disable-pip-version-check `
            --only-binary=:all: `
            --require-hashes `
            --target (Join-Path $OutputPath 'runtime\site-packages') `
            -r (Join-Path $Root 'backend\requirements-windows.lock.txt')
        if ($LASTEXITCODE -ne 0) {
            throw 'Vendoring locked Windows runtime wheels failed.'
        }

        $PthContents = "python313.zip`r`n.`r`nsite-packages`r`n..\backend`r`n"
        [System.IO.File]::WriteAllText(
            (Join-Path $RuntimePath 'python313._pth'),
            $PthContents,
            [System.Text.Encoding]::ASCII
        )

        Copy-Item -LiteralPath (Join-Path $RuntimePath 'LICENSE.txt') `
            -Destination (Join-Path $LicensesPath 'python-LICENSE.txt')
        Copy-Item -LiteralPath (Join-Path $CommittedLicensesPath 'mpv-LICENSE.GPL') `
            -Destination $LicensesPath
        Copy-Item -LiteralPath (Join-Path $CommittedLicensesPath 'cloudflared-LICENSE') `
            -Destination $LicensesPath
        $ComponentTable = @(
            "component`tversion`tsource",
            "python`t$($Lock.python.version)`t$($Lock.python.url)",
            "mpv`t$($Lock.mpv.version)`t$($Lock.mpv.url)",
            "cloudflared`t$($Lock.cloudflared.version)`t$($Lock.cloudflared.url)"
        ) -join "`r`n"
        [System.IO.File]::WriteAllText(
            (Join-Path $LicensesPath 'COMPONENTS.tsv'),
            $ComponentTable + "`r`n",
            [System.Text.UTF8Encoding]::new($false)
        )

        foreach ($ForbiddenPath in @(
            (Join-Path $OutputPath '.venv'),
            (Join-Path $OutputPath 'vendor\adblock'),
            (Join-Path $RuntimePath 'Scripts\pip.exe')
        )) {
            if (Test-Path -LiteralPath $ForbiddenPath) {
                throw "Offline bundle contains forbidden path: $ForbiddenPath"
            }
        }

        $OutputParent = Split-Path -Parent $FinalOutputPath
        if (-not (Test-Path -LiteralPath $OutputParent)) {
            New-Item -ItemType Directory -Force -Path $OutputParent | Out-Null
        }
        if (Test-Path -LiteralPath $FinalOutputPath) {
            Remove-Item -LiteralPath $FinalOutputPath -Recurse -Force
        }
        Move-Item -LiteralPath $OutputPath -Destination $FinalOutputPath
        Write-Host "Wrote verified offline bundle to $FinalOutputPath"
    }
    finally {
        if (Test-Path -LiteralPath $TemporaryRoot) {
            Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-OfflineBundleBuild
}
