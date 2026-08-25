Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ModulePath = Join-Path $PSScriptRoot '..\TVBox.Startup.psm1'
Import-Module (Resolve-Path $ModulePath).Path -Force

Describe 'TVBox.Startup Module Tests' {
    Context 'Settings extraction' {
        It 'handles optional application settings under StrictMode' {
            $MissingApplications = '{"server":{"host":"0.0.0.0","port":8765}}' | ConvertFrom-Json
            $MissingChrome = '{"server":{"host":"0.0.0.0","port":9000},"applications":{"brave_path":"C:\\brave.exe"}}' | ConvertFrom-Json

            $First = Get-StartupSettings -Settings $MissingApplications
            $Second = Get-StartupSettings -Settings $MissingChrome
            $First.Port | Should -Be 8765
            $First.BindHost | Should -Be '0.0.0.0'
            $First.HealthHost | Should -Be '127.0.0.1'
            $First.Transport | Should -Be 'http'
            $First.ConfiguredChromePath | Should -Be ''
            $Second.ConfiguredChromePath | Should -Be ''
        }

        It 'extracts chrome_path and explicit HTTPS transport' {
            $Settings = '{"server":{"host":"0.0.0.0","port":8765,"transport":"https"},"applications":{"chrome_path":"C:\\Custom\\chrome.exe"}}' | ConvertFrom-Json
            $Config = Get-StartupSettings -Settings $Settings

            $Config.Transport | Should -Be 'https'
            $Config.ConfiguredChromePath | Should -Be 'C:\Custom\chrome.exe'
        }

        It 'rejects invalid ports, hosts, transports, and missing server settings' {
            $InvalidPort = '{"server":{"host":"0.0.0.0","port":70000}}' | ConvertFrom-Json
            $InvalidHost = '{"server":{"host":"127.0.0.1","port":8765}}' | ConvertFrom-Json
            $InvalidTransport = '{"server":{"host":"0.0.0.0","port":8765,"transport":"ftp"}}' | ConvertFrom-Json
            $MissingServer = '{"applications":{}}' | ConvertFrom-Json

            { Get-StartupSettings -Settings $InvalidPort } | Should -Throw
            { Get-StartupSettings -Settings $InvalidHost } | Should -Throw
            { Get-StartupSettings -Settings $InvalidTransport } | Should -Throw
            { Get-StartupSettings -Settings $MissingServer } | Should -Throw
        }
    }

    Context 'Controller process ownership' {
        It 'owns exact repository venv production commands independently of TLS arguments' {
            $Python = 'C:\TV Box\freetv\.venv\Scripts\python.exe'
            $Http = '"C:\TV Box\freetv\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --limit-concurrency 64'
            $Https = $Http + ' --ssl-keyfile "C:\TV Box\old.key" --ssl-certfile "C:\TV Box\old.cer"'

            Test-ControllerCommandLineOwnership -CommandLine $Http -PythonPath $Python -Port 8765 | Should -Be $true
            Test-ControllerCommandLineOwnership -CommandLine $Https -PythonPath $Python -Port 8765 | Should -Be $true
        }

        It 'rejects a different Python executable or ASGI app' {
            $Python = 'C:\freetv\.venv\Scripts\python.exe'
            $WrongPython = 'C:\Python311\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765'
            $WrongApp = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn other.main:app --host 0.0.0.0 --port 8765'

            Test-ControllerCommandLineOwnership -CommandLine $WrongPython -PythonPath $Python -Port 8765 | Should -Be $false
            Test-ControllerCommandLineOwnership -CommandLine $WrongApp -PythonPath $Python -Port 8765 | Should -Be $false
        }

        It 'accepts the venv base runtime only with this checkout app directory' {
            $Python = 'C:\freetv\.venv\Scripts\python.exe'
            $BasePython = 'C:\hostedtoolcache\Python\3.11.9\x64\python.exe'
            $Owned = 'C:\hostedtoolcache\Python\3.11.9\x64\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --app-dir C:\freetv\backend'
            $MissingAppDirectory = 'C:\hostedtoolcache\Python\3.11.9\x64\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765'
            $OtherAppDirectory = $MissingAppDirectory + ' --app-dir C:\other\backend'

            Test-ControllerCommandLineOwnership -CommandLine $Owned -PythonPath $Python -BasePythonPath $BasePython -Port 8765 | Should -Be $true
            Test-ControllerCommandLineOwnership -CommandLine $MissingAppDirectory -PythonPath $Python -BasePythonPath $BasePython -Port 8765 | Should -Be $false
            Test-ControllerCommandLineOwnership -CommandLine $OtherAppDirectory -PythonPath $Python -BasePythonPath $BasePython -Port 8765 | Should -Be $false
            Test-ControllerCommandLineOwnership -CommandLine $Owned -PythonPath $Python -BasePythonPath 'C:\other\python.exe' -Port 8765 | Should -Be $false
        }

        It 'requires the actual process executable to match the repository venv' {
            $Python = 'C:\freetv\.venv\Scripts\python.exe'
            $CommandLine = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765'
            $Owned = [PSCustomObject]@{ ExecutablePath = $Python; CommandLine = $CommandLine }
            $Spoofed = [PSCustomObject]@{ ExecutablePath = 'C:\other\python.exe'; CommandLine = $CommandLine }

            Test-ControllerProcessOwnership -Process $Owned -PythonPath $Python -Port 8765 | Should -Be $true
            Test-ControllerProcessOwnership -Process $Spoofed -PythonPath $Python -Port 8765 | Should -Be $false
        }

        It 'does not own a base-runtime process without its venv parent' {
            $Python = 'C:\freetv\.venv\Scripts\python.exe'
            $BaseCommandLine = 'C:\Python311\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --app-dir C:\freetv\backend'
            $VenvCommandLine = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --app-dir C:\freetv\backend'
            $Owned = [PSCustomObject]@{ ExecutablePath = 'C:\Python311\python.exe'; CommandLine = $BaseCommandLine }
            $Mismatched = [PSCustomObject]@{ ExecutablePath = 'C:\Python311\python.exe'; CommandLine = $VenvCommandLine }

            Test-ControllerProcessOwnership -Process $Owned -PythonPath $Python -Port 8765 | Should -Be $false
            Test-ControllerProcessOwnership -Process $Mismatched -PythonPath $Python -Port 8765 | Should -Be $false
        }

        It 'accepts the Windows venv launcher and base-Python child topology only as one owned tree' {
            $Python = 'C:\freetv\.venv\Scripts\python.exe'
            $CommandLine = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --app-dir C:\freetv\backend'
            $BaseCommandLine = 'C:\Python314\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --app-dir C:\freetv\backend'
            $Child = [PSCustomObject]@{
                ProcessId = 202
                ParentProcessId = 101
                ExecutablePath = 'C:\Python314\python.exe'
                CommandLine = $CommandLine
            }
            $Parent = [PSCustomObject]@{
                ProcessId = 101
                ParentProcessId = 50
                ExecutablePath = $Python
                CommandLine = $CommandLine
            }
            $WrongParent = [PSCustomObject]@{
                ProcessId = 999
                ParentProcessId = 50
                ExecutablePath = $Python
                CommandLine = $CommandLine
            }
            $ForeignParent = [PSCustomObject]@{
                ProcessId = 101
                ParentProcessId = 50
                ExecutablePath = 'C:\other\python.exe'
                CommandLine = 'C:\other\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --app-dir C:\freetv\backend'
            }
            $WrongChildExecutable = [PSCustomObject]@{
                ProcessId = 303
                ParentProcessId = 101
                ExecutablePath = 'C:\other\python.exe'
                CommandLine = $CommandLine
            }
            $BaseCommandChild = [PSCustomObject]@{
                ProcessId = 404
                ParentProcessId = 101
                ExecutablePath = 'C:\Python314\python.exe'
                CommandLine = $BaseCommandLine
            }
            $BaseChildWithoutAppDirectory = [PSCustomObject]@{
                ProcessId = 505
                ParentProcessId = 101
                ExecutablePath = 'C:\Python314\python.exe'
                CommandLine = 'C:\Python314\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765'
            }

            Test-ControllerProcessTreeOwnership -Process $Child -ParentProcess $Parent -PythonPath $Python -BasePythonPath 'C:\Python314\python.exe' -Port 8765 | Should -Be $true
            Test-ControllerProcessTreeOwnership -Process $BaseCommandChild -ParentProcess $Parent -PythonPath $Python -BasePythonPath 'C:\Python314\python.exe' -Port 8765 | Should -Be $true
            Test-ControllerProcessTreeOwnership -Process $BaseCommandChild -ParentProcess $null -PythonPath $Python -BasePythonPath 'C:\Python314\python.exe' -Port 8765 | Should -Be $false
            Test-ControllerProcessTreeOwnership -Process $BaseCommandChild -ParentProcess $Parent -PythonPath $Python -Port 8765 | Should -Be $false
            Test-ControllerProcessTreeOwnership -Process $BaseChildWithoutAppDirectory -ParentProcess $Parent -PythonPath $Python -BasePythonPath 'C:\Python314\python.exe' -Port 8765 | Should -Be $false
            Test-ControllerProcessTreeOwnership -Process $Child -ParentProcess $WrongParent -PythonPath $Python -BasePythonPath 'C:\Python314\python.exe' -Port 8765 | Should -Be $false
            Test-ControllerProcessTreeOwnership -Process $Child -ParentProcess $ForeignParent -PythonPath $Python -BasePythonPath 'C:\Python314\python.exe' -Port 8765 | Should -Be $false
            Test-ControllerProcessTreeOwnership -Process $WrongChildExecutable -ParentProcess $Parent -PythonPath $Python -BasePythonPath 'C:\Python314\python.exe' -Port 8765 | Should -Be $false
        }

        It 'rejects loopback or duplicate host bindings' {
            $Python = 'C:\freetv\.venv\Scripts\python.exe'
            $Loopback = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765'
            $Duplicate = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --host 127.0.0.1 --port 8765'

            Test-ControllerCommandLineOwnership -CommandLine $Loopback -PythonPath $Python -Port 8765 | Should -Be $false
            Test-ControllerCommandLineOwnership -CommandLine $Duplicate -PythonPath $Python -Port 8765 | Should -Be $false
        }

        It 'rejects different or duplicate ports and development process modes' {
            $Python = 'C:\freetv\.venv\Scripts\python.exe'
            $WrongPort = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9000'
            $DuplicatePort = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --port 9000'
            $Reload = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --reload'
            $Workers = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --workers=2'

            Test-ControllerCommandLineOwnership -CommandLine $WrongPort -PythonPath $Python -Port 8765 | Should -Be $false
            Test-ControllerCommandLineOwnership -CommandLine $DuplicatePort -PythonPath $Python -Port 8765 | Should -Be $false
            Test-ControllerCommandLineOwnership -CommandLine $Reload -PythonPath $Python -Port 8765 | Should -Be $false
            Test-ControllerCommandLineOwnership -CommandLine $Workers -PythonPath $Python -Port 8765 | Should -Be $false
        }

        It 'accepts only this repository backend when app-dir is explicit' {
            $Python = 'C:\freetv\.venv\Scripts\python.exe'
            $Legacy = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765'
            $Owned = $Legacy + ' --app-dir C:\freetv\backend'
            $Other = $Legacy + ' --app-dir C:\other\backend'

            Test-ControllerCommandLineOwnership -CommandLine $Legacy -PythonPath $Python -Port 8765 | Should -Be $true
            Test-ControllerCommandLineOwnership -CommandLine $Owned -PythonPath $Python -Port 8765 | Should -Be $true
            Test-ControllerCommandLineOwnership -CommandLine $Other -PythonPath $Python -Port 8765 | Should -Be $false
        }
    }

    Context 'Controller transport and certificate matching' {
        It 'matches HTTP only when TLS arguments are absent' {
            $Http = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765'
            $Https = $Http + ' --ssl-keyfile C:\freetv\config\tls\server.key --ssl-certfile C:\freetv\config\tls\server.cer'

            Test-ControllerCommandLineTransport -CommandLine $Http -Transport http | Should -Be $true
            Test-ControllerCommandLineTransport -CommandLine $Https -Transport http | Should -Be $false
        }

        It 'matches HTTPS only with the current certificate and key paths' {
            $Certificate = 'C:\TV Box\freetv\config\tls\server.cer'
            $PrivateKey = 'C:\TV Box\freetv\config\tls\server.key'
            $CommandLine = '"C:\TV Box\freetv\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --ssl-keyfile "C:\TV Box\freetv\config\tls\server.key" --ssl-certfile "C:\TV Box\freetv\config\tls\server.cer"'

            Test-ControllerCommandLineTransport -CommandLine $CommandLine -Transport https -CertificatePath $Certificate -PrivateKeyPath $PrivateKey | Should -Be $true
            Test-ControllerCommandLineTransport -CommandLine $CommandLine -Transport https -CertificatePath 'C:\old.cer' -PrivateKeyPath $PrivateKey | Should -Be $false
        }

        It 'matches equals-form TLS arguments containing spaces' {
            $CommandLine = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --ssl-keyfile="C:\TV Box\server.key" --ssl-certfile="C:\TV Box\server.cer"'

            Test-ControllerCommandLineTransport -CommandLine $CommandLine -Transport https -CertificatePath 'C:\TV Box\server.cer' -PrivateKeyPath 'C:\TV Box\server.key' | Should -Be $true
        }

        It 'marks HTTP to HTTPS and HTTPS to HTTP switches as mismatches' {
            $Http = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765'
            $Https = $Http + ' --ssl-keyfile C:\freetv\config\tls\server.key --ssl-certfile C:\freetv\config\tls\server.cer'

            Test-ControllerCommandLineTransport -CommandLine $Http -Transport https -CertificatePath 'C:\freetv\config\tls\server.cer' -PrivateKeyPath 'C:\freetv\config\tls\server.key' | Should -Be $false
            Test-ControllerCommandLineTransport -CommandLine $Https -Transport http | Should -Be $false
        }

        It 'rejects duplicate TLS path arguments' {
            $CommandLine = 'C:\freetv\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --ssl-keyfile C:\freetv\config\tls\server.key --ssl-certfile C:\old.cer --ssl-certfile C:\server.cer'

            Test-ControllerCommandLineTransport -CommandLine $CommandLine -Transport https -CertificatePath 'C:\server.cer' -PrivateKeyPath 'C:\freetv\config\tls\server.key' | Should -Be $false
        }

        It 'detects certificate files written after process startup' {
            $CertificateWrite = [datetime]'2026-08-23T10:00:00Z'

            Test-ControllerCertificateFreshness -ProcessCreationDate ([datetime]'2026-08-23T10:00:01Z') -CertificateLastWriteTimeUtc $CertificateWrite | Should -Be $true
            Test-ControllerCertificateFreshness -ProcessCreationDate $CertificateWrite -CertificateLastWriteTimeUtc $CertificateWrite | Should -Be $true
            Test-ControllerCertificateFreshness -ProcessCreationDate ([datetime]'2026-08-23T09:59:59Z') -CertificateLastWriteTimeUtc $CertificateWrite | Should -Be $false
            Test-ControllerCertificateFreshness -ProcessCreationDate $null -CertificateLastWriteTimeUtc $CertificateWrite | Should -Be $false
        }
    }

    Context 'Python runtime selection' {
        It 'accepts 3.11+ and rejects old or invalid existing runtime versions' {
            Test-PythonRuntimeVersion -VersionValue '3.11.0' | Should -Be $true
            Test-PythonRuntimeVersion -VersionValue ([version]'3.14.2') | Should -Be $true
            Test-PythonRuntimeVersion -VersionValue '3.10.14' | Should -Be $false
            Test-PythonRuntimeVersion -VersionValue 'not-a-version' | Should -Be $false
        }

        It 'requires an existing runtime to be an isolated project venv' {
            $Valid = [PSCustomObject]@{ Version = [version]'3.12.6'; Prefix = 'C:\freetv\.venv'; BasePrefix = 'C:\Python312' }
            $GlobalCopy = [PSCustomObject]@{ Version = [version]'3.12.6'; Prefix = 'C:\Python312'; BasePrefix = 'C:\Python312' }
            $WrongProject = [PSCustomObject]@{ Version = [version]'3.12.6'; Prefix = 'C:\other\.venv'; BasePrefix = 'C:\Python312' }

            Test-PythonVirtualEnvironmentRuntime -Runtime $Valid -ExpectedDirectory 'C:\freetv\.venv' | Should -Be $true
            Test-PythonVirtualEnvironmentRuntime -Runtime $GlobalCopy -ExpectedDirectory 'C:\freetv\.venv' | Should -Be $false
            Test-PythonVirtualEnvironmentRuntime -Runtime $WrongProject -ExpectedDirectory 'C:\freetv\.venv' | Should -Be $false
        }

        It 'falls back from old PATH Python to a qualifying py launcher runtime' {
            $Candidates = @(
                [PSCustomObject]@{ Executable = 'C:\Python310\python.exe'; PrefixArguments = @(); DisplayName = 'python on PATH'; Version = [version]'3.10.14' },
                [PSCustomObject]@{ Executable = 'C:\Windows\py.exe'; PrefixArguments = @('-3'); DisplayName = 'py -3'; Version = [version]'3.12.6' }
            )

            $Selected = Select-PythonRuntimeCandidate -Candidates $Candidates
            $Selected.DisplayName | Should -Be 'py -3'
            @($Selected.PrefixArguments) | Should -Be @('-3')
        }

        It 'prefers the first qualifying runtime and rejects malformed candidates' {
            $Candidates = @(
                [PSCustomObject]@{ Executable = 'C:\Python311\python.exe'; Version = [version]'3.11.9'; DisplayName = 'python on PATH' },
                [PSCustomObject]@{ Executable = 'C:\Windows\py.exe'; Version = [version]'3.14.0'; DisplayName = 'py -3' }
            )
            $Invalid = @(
                [PSCustomObject]@{ Executable = 'C:\Python310\python.exe'; Version = [version]'3.10.14' },
                [PSCustomObject]@{ Executable = ''; Version = [version]'3.14.0' },
                [PSCustomObject]@{ Executable = 'C:\broken.exe'; Version = 'broken' }
            )

            (Select-PythonRuntimeCandidate -Candidates $Candidates).DisplayName | Should -Be 'python on PATH'
            Select-PythonRuntimeCandidate -Candidates $Invalid | Should -BeNullOrEmpty
        }

        It 'moves an unusable project venv aside' {
            $Venv = Join-Path $TestDrive 'venv-source'
            New-Item -ItemType Directory -Path $Venv | Out-Null
            New-Item -ItemType File -Path (Join-Path $Venv 'marker.txt') | Out-Null

            $Moved = Move-UnusableProjectVenv -VenvDirectory $Venv

            Test-Path -LiteralPath $Venv | Should -Be $false
            Test-Path -LiteralPath $Moved | Should -Be $true
            Test-Path -LiteralPath (Join-Path $Moved 'marker.txt') | Should -Be $true
        }

    }

    Context 'Browser and pairing argument construction' {
        It 'constructs isolated Chrome fullscreen arguments' {
            $Url = 'https://127.0.0.1:8765/tv'
            $Arguments = Get-ChromeLauncherKioskArguments -Url $Url -UserDataDir 'C:\TV Box\config\chrome-launcher-profile'

            $Arguments | Should -Contain '--start-fullscreen'
            $Arguments | Should -Contain $Url
            $Arguments | Should -Contain '--no-first-run'
            $Arguments | Should -Contain '--no-default-browser-check'
            $Arguments | Should -Contain '--hide-crash-restore-bubble'
            $Arguments | Should -Contain '--noerrdialogs'
            $Arguments | Should -Contain '--user-data-dir="C:\TV Box\config\chrome-launcher-profile"'
            $Arguments | Should -Contain '--disable-extensions'
            $Arguments | Should -Contain '--disable-sync'
            $Arguments | Should -Not -Contain '--kiosk'
        }

        It 'keeps normal browser arguments separate and resolves the kiosk path' {
            $Arguments = Get-BrowserLaunchArguments -Url 'https://127.0.0.1:8765/tv'

            Get-LauncherUserDataDirectory -RootDirectory 'C:\freetv' | Should -Be 'C:\freetv\config\chrome-launcher-profile'
            $Arguments | Should -Contain 'https://127.0.0.1:8765/tv'
            (-not ($Arguments -match '--user-data-dir')) | Should -Be $true
            (-not ($Arguments -match '--kiosk')) | Should -Be $true
            (-not ($Arguments -match '--start-fullscreen')) | Should -Be $true
        }

        It 'uses the backend pairing URL and preserves fallback scheme' {
            $PairingResponse = [PSCustomObject]@{ remote_url = 'https://192.168.1.44:8765/remote' }

            Get-PairingRemoteUrl -PairingResponse $PairingResponse -Port 8765 | Should -Be 'https://192.168.1.44:8765/remote'
            Get-PairingRemoteUrl -PairingResponse ([PSCustomObject]@{}) -Port 9000 -Scheme https | Should -Be 'https://<PC-LAN-IP>:9000/remote'
        }
    }

    Context 'Autostart task object construction' {
        It 'builds a finite, battery-safe task specification' {
            $Spec = Get-AutostartTaskSpec -StartScriptPath 'C:\freetv\scripts\start.ps1' -TaskName 'PC TV Box'

            $Spec.TaskName | Should -Be 'PC TV Box'
            $Spec.Argument | Should -Be '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\freetv\scripts\start.ps1" -Supervise'
            $Spec.UserId | Should -Be ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
            $Spec.TriggerType | Should -Be 'AtLogOn'
            $Spec.StartWhenAvailable | Should -Be $true
            $Spec.AllowStartIfOnBatteries | Should -Be $true
            $Spec.DontStopIfGoingOnBatteries | Should -Be $true
            $Spec.ExecutionTimeLimitMinutes | Should -Be 0
            $Spec.RestartCount | Should -Be 3
            $Spec.RestartIntervalMinutes | Should -Be 1
        }

        It 'limits the logon trigger to the registering Windows user' {
            $UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            $Trigger = New-AutostartTaskTrigger -UserId $UserId

            $Trigger.UserId | Should -Be $UserId
        }

        It 'creates battery-safe settings with bounded restart behavior' {
            $Settings = New-AutostartTaskSettings

            $Settings.StartWhenAvailable | Should -Be $true
            $Settings.DisallowStartIfOnBatteries | Should -Be $false
            $Settings.StopIfGoingOnBatteries | Should -Be $false
            $Settings.ExecutionTimeLimit | Should -Be 'PT0S'
            $Settings.RestartCount | Should -Be 3
            $Settings.RestartInterval | Should -Be 'PT1M'
        }

        It 'recognizes only this checkout current or legacy autostart action' {
            $Current = [PSCustomObject]@{
                Actions = @([PSCustomObject]@{
                    Execute = 'powershell.exe'
                    Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\freetv\scripts\start.ps1" -Supervise'
                })
            }
            $Legacy = [PSCustomObject]@{
                Actions = @([PSCustomObject]@{
                    Execute = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
                    Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\freetv\scripts\start.ps1"'
                })
            }
            $Foreign = [PSCustomObject]@{
                Actions = @([PSCustomObject]@{
                    Execute = 'powershell.exe'
                    Arguments = '-NoProfile -File "C:\other\start.ps1" -Supervise'
                })
            }

            Test-AutostartTaskOwnership -Task $Current -StartScriptPath 'C:\freetv\scripts\start.ps1' | Should -Be $true
            Test-AutostartTaskOwnership -Task $Legacy -StartScriptPath 'C:\freetv\scripts\start.ps1' | Should -Be $true
            Test-AutostartTaskOwnership -Task $Foreign -StartScriptPath 'C:\freetv\scripts\start.ps1' | Should -Be $false
        }

        It 'refuses to replace a foreign same-name scheduled task' {
            Mock Get-ScheduledTask -ModuleName TVBox.Startup {
                [PSCustomObject]@{
                    Actions = @([PSCustomObject]@{
                        Execute = 'powershell.exe'
                        Arguments = '-NoProfile -File "C:\other\start.ps1"'
                    })
                }
            }
            Mock Register-ScheduledTask -ModuleName TVBox.Startup { throw 'must not register' }

            {
                Install-AutostartTask -StartScriptPath 'C:\freetv\scripts\start.ps1' -TaskName 'PC TV Box'
            } | Should -Throw '*not owned by this checkout*'
            Should -Invoke Register-ScheduledTask -ModuleName TVBox.Startup -Times 0 -Exactly
        }

        It 'refuses to remove a foreign same-name scheduled task' {
            Mock Get-ScheduledTask -ModuleName TVBox.Startup {
                [PSCustomObject]@{
                    Actions = @([PSCustomObject]@{
                        Execute = 'powershell.exe'
                        Arguments = '-NoProfile -File "C:\other\start.ps1"'
                    })
                }
            }
            Mock Unregister-ScheduledTask -ModuleName TVBox.Startup { throw 'must not unregister' }

            {
                Remove-AutostartTask -StartScriptPath 'C:\freetv\scripts\start.ps1' -TaskName 'PC TV Box'
            } | Should -Throw '*not owned by this checkout*'
            Should -Invoke Unregister-ScheduledTask -ModuleName TVBox.Startup -Times 0 -Exactly
        }
    }

    Context 'Optional winget installs' {
        It 'normalizes an accepted winget result before returning to setup callers' {
            $FakeWinget = Join-Path $TestDrive 'winget.cmd'
            Set-Content -LiteralPath $FakeWinget -Encoding Ascii -Value @(
                '@echo off'
                'exit /b -1978335189'
            )
            Mock Get-Command -ModuleName TVBox.Startup {
                [PSCustomObject]@{ Source = $FakeWinget }
            } -ParameterFilter { $Name -eq 'winget' }

            $global:LASTEXITCODE = 0
            try {
                Install-WingetPackage -PackageId 'fixture.package' -DisplayName 'fixture' |
                    Should -Be $true
                $global:LASTEXITCODE | Should -Be 0
            } finally {
                $global:LASTEXITCODE = 0
            }
        }
    }
}
