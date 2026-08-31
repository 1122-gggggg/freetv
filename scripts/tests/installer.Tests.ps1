param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
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
                    '-File \"{0}\" -Supervise'
                ) -f (Join-Path $InstallRoot 'scripts\start.ps1')
                $Actions = $Task.Definition.Actions
                $Owned = $false
                if ($Actions.Count -eq 1) {
                    $Action = $Actions.Item(1)
                    $Owned = (
                        $Action.Type -eq 0 -and
                        [IO.Path]::GetFileName([string]$Action.Path) -ieq
                            'powershell.exe' -and
                        [string]$Action.Arguments -ieq $ExpectedArguments
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
}
