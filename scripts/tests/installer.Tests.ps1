param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

BeforeAll {
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

    It 'starts a healthy local controller after installation' {
        $Health = $null
        $Deadline = [DateTime]::UtcNow.AddSeconds(30)
        while ([DateTime]::UtcNow -lt $Deadline) {
            try {
                $Health = Invoke-RestMethod `
                    -Uri 'http://127.0.0.1:8765/api/health' `
                    -TimeoutSec 2
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

        $Health.status | Should -Be 'ok'
        $Health.backend | Should -BeTrue
        $Health.frontend | Should -BeTrue
    }

    It 'removes the legacy scheduled task' {
        $null = & schtasks.exe /Query /TN 'PC TV Box' 2>&1
        $LASTEXITCODE | Should -Not -Be 0
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
