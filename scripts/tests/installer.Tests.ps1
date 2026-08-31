param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,
    [string]$InstallerPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

BeforeAll {
    $ExpectedPython = Join-Path $InstallRoot 'runtime\python.exe'
    $ExpectedPythonw = Join-Path $InstallRoot 'runtime\pythonw.exe'
    $ExpectedLauncherArguments = '"{0}" start' -f (Join-Path $InstallRoot 'freetv.py')
    $StartMenuShortcut = Join-Path `
        ([Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)) `
        'FreeTV.lnk'
    $DesktopShortcut = Join-Path `
        ([Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)) `
        'FreeTV.lnk'
    $StartupShortcut = Join-Path `
        ([Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)) `
        'FreeTV.lnk'
    $Settings = Get-Content -Raw -LiteralPath `
        (Join-Path $InstallRoot 'config\settings.json') |
        ConvertFrom-Json
    $InstalledPort = [int]$Settings.server.port
    $InstalledTransport = [string]$Settings.server.transport
    if ($InstalledTransport -notin @('http', 'https')) {
        throw "Unsupported installed transport: $InstalledTransport"
    }
    $HealthUri = '{0}://127.0.0.1:{1}/api/health' -f `
        $InstalledTransport, $InstalledPort

    function Get-ShortcutState {
        param([Parameter(Mandatory = $true)][string]$Path)

        $Shell = New-Object -ComObject WScript.Shell
        try {
            $Shortcut = $Shell.CreateShortcut($Path)
            return [pscustomobject]@{
                TargetPath = $Shortcut.TargetPath
                Arguments = $Shortcut.Arguments
                WorkingDirectory = $Shortcut.WorkingDirectory
            }
        }
        finally {
            if ($null -ne $Shell) {
                [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($Shell)
            }
        }
    }

    function Get-LegacyScheduledTaskState {
        $Scheduler = New-Object -ComObject Schedule.Service
        try {
            $Scheduler.Connect()
            $RootFolder = $Scheduler.GetFolder('\')
            $Tasks = $RootFolder.GetTasks(0)
            for ($Index = 1; $Index -le $Tasks.Count; $Index++) {
                $Task = $Tasks.Item($Index)
                if ($Task.Name -ine 'PC TV Box') {
                    continue
                }

                $ExpectedArguments = (
                    '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden ' +
                    '-File "{0}" -Supervise'
                ) -f (Join-Path $InstallRoot 'scripts\start.ps1')
                $LegacyArguments = $ExpectedArguments.Substring(
                    0,
                    $ExpectedArguments.Length - ' -Supervise'.Length
                )
                $Actions = $Task.Definition.Actions
                $Owned = $false
                if ($Actions.Count -eq 1) {
                    $Action = $Actions.Item(1)
                    $Owned = (
                        $Action.Type -eq 0 -and
                        [IO.Path]::GetFileName([string]$Action.Path) -ieq
                            'powershell.exe' -and
                        (
                            [string]$Action.Arguments -ieq $ExpectedArguments -or
                            [string]$Action.Arguments -ieq $LegacyArguments
                        )
                    )
                }
                return [pscustomobject]@{
                    Exists = $true
                    Owned = $Owned
                }
            }

            return [pscustomobject]@{
                Exists = $false
                Owned = $false
            }
        }
        finally {
            if ($null -ne $Scheduler) {
                [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject(
                    $Scheduler
                )
            }
        }
    }
}

Describe 'Offline FreeTV installation' {
    It 'uses the bundled runtime without a virtual environment' {
        Test-Path (Join-Path $InstallRoot 'runtime\python.exe') | Should -BeTrue
        Test-Path (Join-Path $InstallRoot 'runtime\pythonw.exe') | Should -BeTrue
        Test-Path (Join-Path $InstallRoot '.venv') | Should -BeFalse
    }

    It 'contains both bundled tools' {
        Test-Path (Join-Path $InstallRoot 'tools\mpv\mpv.exe') | Should -BeTrue
        Test-Path (Join-Path $InstallRoot 'tools\cloudflared\cloudflared.exe') | Should -BeTrue
    }

    It 'has a healthy private runtime' {
        & (Join-Path $InstallRoot 'runtime\python.exe') -c `
            'import fastapi, uvicorn, cryptography, pycaw, zeroconf'
        $LASTEXITCODE | Should -Be 0
    }

    It 'starts a healthy local controller from the installed runtime' {
        $Health = $null
        $PreviousCertificateCallback =
            [Net.ServicePointManager]::ServerCertificateValidationCallback
        try {
            if ($InstalledTransport -eq 'https') {
                [Net.ServicePointManager]::ServerCertificateValidationCallback = {
                    $true
                }
            }

            $Deadline = [DateTime]::UtcNow.AddSeconds(30)
            while ([DateTime]::UtcNow -lt $Deadline) {
                try {
                    $Health = Invoke-RestMethod -Uri $HealthUri -TimeoutSec 2
                    if (
                        $Health.status -eq 'ok' -and
                        $Health.backend -eq $true -and
                        $Health.frontend -eq $true
                    ) {
                        break
                    }
                }
                catch {
                    Start-Sleep -Milliseconds 500
                }
            }
        }
        finally {
            [Net.ServicePointManager]::ServerCertificateValidationCallback =
                $PreviousCertificateCallback
        }

        $Health.status | Should -Be 'ok'
        $Health.backend | Should -BeTrue
        $Health.frontend | Should -BeTrue

        $Connections = @(
            Get-NetTCPConnection -LocalPort $InstalledPort -State Listen
        )
        $Connections.Count | Should -BeGreaterThan 0
        $ControllerProcesses = @(
            $Connections.OwningProcess |
                Sort-Object -Unique |
                ForEach-Object {
                    Get-CimInstance Win32_Process -Filter "ProcessId=$_"
                } |
                Where-Object {
                    $_.ExecutablePath -ieq $ExpectedPython
                }
        )
        $ControllerProcesses.Count | Should -Be 1
        $ControllerProcesses[0].CommandLine | Should -Match (
            [regex]::Escape($InstallRoot)
        )
    }

    It 'does not leave an owned legacy scheduled task' {
        $TaskState = Get-LegacyScheduledTaskState
        $TaskState.Owned | Should -BeFalse
    }

    It 'installs a Start Menu launcher that uses pythonw' {
        Test-Path -LiteralPath $StartMenuShortcut | Should -BeTrue
        $Shortcut = Get-ShortcutState -Path $StartMenuShortcut
        $Shortcut.TargetPath | Should -Be $ExpectedPythonw
        $Shortcut.Arguments | Should -Be $ExpectedLauncherArguments
        $Shortcut.WorkingDirectory | Should -Be $InstallRoot
    }

    It 'selects the desktop launcher by default' {
        Test-Path -LiteralPath $DesktopShortcut | Should -BeTrue
        $Shortcut = Get-ShortcutState -Path $DesktopShortcut
        $Shortcut.TargetPath | Should -Be $ExpectedPythonw
        $Shortcut.Arguments | Should -Be $ExpectedLauncherArguments
        $Shortcut.WorkingDirectory | Should -Be $InstallRoot
    }

    It 'selects supervised autostart by default' {
        Test-Path -LiteralPath $StartupShortcut | Should -BeTrue
        $Shortcut = Get-ShortcutState -Path $StartupShortcut
        $Shortcut.TargetPath | Should -Be $ExpectedPythonw
        $Shortcut.Arguments | Should -Be "$ExpectedLauncherArguments --supervise"
        $Shortcut.WorkingDirectory | Should -Be $InstallRoot
    }

    It 'removes obsolete managed files on upgrade while preserving config, logs, and user settings' {
        $ResolvedInstaller = if (-not [string]::IsNullOrWhiteSpace($InstallerPath) -and (Test-Path -LiteralPath $InstallerPath)) {
            (Resolve-Path -LiteralPath $InstallerPath).Path
        } else {
            $Candidate = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'FreeTV-Setup.exe'
            if (Test-Path -LiteralPath $Candidate) { (Resolve-Path -LiteralPath $Candidate).Path } else { $null }
        }
        if ($null -eq $ResolvedInstaller) {
            throw "FreeTV-Setup.exe was not found. Please build the installer first or pass -InstallerPath."
        }

        $ObsoleteBackend = Join-Path $InstallRoot 'backend\app\adblock.py'
        $ObsoleteVendor = Join-Path $InstallRoot 'vendor\adblock-rules.txt'
        $ObsoleteScripts = Join-Path $InstallRoot 'scripts\obsolete-script.ps1'
        $ObsoleteTools = Join-Path $InstallRoot 'tools\obsolete-tool.exe'

        $CustomConfigFile = Join-Path $InstallRoot 'config\user-custom.json'
        $CustomLogFile = Join-Path $InstallRoot 'logs\custom-install.log'

        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ObsoleteBackend) | Out-Null
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ObsoleteVendor) | Out-Null
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ObsoleteScripts) | Out-Null
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ObsoleteTools) | Out-Null
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CustomConfigFile) | Out-Null
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CustomLogFile) | Out-Null

        Set-Content -LiteralPath $ObsoleteBackend -Value '# obsolete adblock module' -Encoding utf8
        Set-Content -LiteralPath $ObsoleteVendor -Value 'obsolete vendor rules' -Encoding utf8
        Set-Content -LiteralPath $ObsoleteScripts -Value '# obsolete helper' -Encoding utf8
        Set-Content -LiteralPath $ObsoleteTools -Value 'obsolete tool binary' -Encoding utf8
        Set-Content -LiteralPath $CustomConfigFile -Value '{"custom_setting": 123}' -Encoding utf8
        Set-Content -LiteralPath $CustomLogFile -Value '2026-08-31 custom log entry' -Encoding utf8

        $Process = Start-Process `
            -FilePath $ResolvedInstaller `
            -ArgumentList @(
                '/VERYSILENT',
                '/SUPPRESSMSGBOXES',
                '/NORESTART',
                '/UPDATE=1',
                ('/DIR="{0}"' -f $InstallRoot),
                '/MERGETASKS="!appliancepower"'
            ) `
            -PassThru
        $Process.WaitForExit(60000) | Should -BeTrue
        $Process.ExitCode | Should -Be 0

        Test-Path -LiteralPath $ObsoleteBackend | Should -BeFalse
        Test-Path -LiteralPath $ObsoleteVendor | Should -BeFalse
        Test-Path -LiteralPath $ObsoleteScripts | Should -BeFalse
        Test-Path -LiteralPath $ObsoleteTools | Should -BeFalse

        Test-Path -LiteralPath $CustomConfigFile | Should -BeTrue
        (Get-Content -Raw -LiteralPath $CustomConfigFile) | Should -Match '"custom_setting": 123'

        Test-Path -LiteralPath $CustomLogFile | Should -BeTrue
        (Get-Content -Raw -LiteralPath $CustomLogFile) | Should -Match 'custom log entry'

        Test-Path -LiteralPath (Join-Path $InstallRoot 'runtime\python.exe') | Should -BeTrue
        Test-Path -LiteralPath (Join-Path $InstallRoot 'backend\app\installer.py') | Should -BeTrue
        Test-Path -LiteralPath (Join-Path $InstallRoot 'freetv.py') | Should -BeTrue
    }
}
