Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ModulePath = Join-Path $PSScriptRoot '..\TVBox.Startup.psm1'
Import-Module (Resolve-Path $ModulePath).Path -Force

if (-not (Get-Command -Name Describe -ErrorAction SilentlyContinue)) {
    Import-Module Pester -ErrorAction SilentlyContinue
}

if (Get-Command -Name Describe -ErrorAction SilentlyContinue) {
    Describe 'TVBox.Startup Module Tests' {
        Context 'Settings Extraction and StrictMode Resiliency' {
            It 'Handles missing applications section under StrictMode defaulting to empty edge_path' {
                $Settings = '{"server":{"host":"0.0.0.0","port":8765}}' | ConvertFrom-Json
                $Config = Get-StartupSettings -Settings $Settings
                $Config.Port | Should -Be 8765
                $Config.BindHost | Should -Be '0.0.0.0'
                $Config.HealthHost | Should -Be '127.0.0.1'
                $Config.Transport | Should -Be 'http'
                $Config.ConfiguredEdgePath | Should -Be ''
            }

            It 'Handles missing edge_path in applications under StrictMode defaulting to empty' {
                $Settings = '{"server":{"host":"0.0.0.0","port":9000},"applications":{"brave_path":"C:\\brave.exe"}}' | ConvertFrom-Json
                $Config = Get-StartupSettings -Settings $Settings
                $Config.Port | Should -Be 9000
                $Config.BindHost | Should -Be '0.0.0.0'
                $Config.HealthHost | Should -Be '127.0.0.1'
                $Config.ConfiguredEdgePath | Should -Be ''
            }

            It 'Extracts configured edge_path when present' {
                $Settings = '{"server":{"host":"0.0.0.0","port":8765},"applications":{"edge_path":"C:\\Custom\\msedge.exe"}}' | ConvertFrom-Json
                $Config = Get-StartupSettings -Settings $Settings
                $Config.ConfiguredEdgePath | Should -Be 'C:\Custom\msedge.exe'
            }

            It 'Rejects invalid port or missing server configuration' {
                $InvalidPortSettings = '{"server":{"host":"0.0.0.0","port":70000}}' | ConvertFrom-Json
                { Get-StartupSettings -Settings $InvalidPortSettings } | Should -Throw

                $MissingServerSettings = '{"applications":{}}' | ConvertFrom-Json
                { Get-StartupSettings -Settings $MissingServerSettings } | Should -Throw

                $UnsupportedHostSettings = '{"server":{"host":"127.0.0.1","port":8765}}' | ConvertFrom-Json
                { Get-StartupSettings -Settings $UnsupportedHostSettings } | Should -Throw
            }

            It 'Defaults transport to http when absent' {
                $Settings = '{"server":{"host":"0.0.0.0","port":8765}}' | ConvertFrom-Json
                $Config = Get-StartupSettings -Settings $Settings
                $Config.Transport | Should -Be 'http'
            }

            It 'Parses explicit https transport' {
                $Settings = '{"server":{"host":"0.0.0.0","port":8765,"transport":"https"}}' | ConvertFrom-Json
                $Config = Get-StartupSettings -Settings $Settings
                $Config.Transport | Should -Be 'https'
            }

            It 'Rejects invalid transport' {
                $InvalidTransportSettings = '{"server":{"host":"0.0.0.0","port":8765,"transport":"ftp"}}' | ConvertFrom-Json
                { Get-StartupSettings -Settings $InvalidTransportSettings } | Should -Throw
            }
        }

        Context 'Kiosk Profile and Browser Argument Construction' {
            It 'Constructs Edge kiosk arguments with dedicated profile user-data-dir and kiosk flags' {
                $Url = 'https://127.0.0.1:8765/tv'
                $UserDataDir = 'C:\TV Box\config\edge-profile'
                $Args = Get-EdgeKioskArguments -Url $Url -UserDataDir $UserDataDir

                ($Args -contains '--kiosk') | Should -Be $true
                ($Args -contains $Url) | Should -Be $true
                ($Args -contains '--edge-kiosk-type=fullscreen') | Should -Be $true
                ($Args -contains '--no-first-run') | Should -Be $true
                ($Args -contains '--user-data-dir="C:\TV Box\config\edge-profile"') | Should -Be $true
                ($Args -contains '--disable-extensions') | Should -Be $true
                ($Args -contains '--disable-sync') | Should -Be $true
            }

            It 'Resolves absolute kiosk user-data-dir path under ignored config state' {
                $Dir = Get-EdgeUserDataDirectory -RootDirectory 'C:\freetv'
                $Dir | Should -Be 'C:\freetv\config\edge-profile'
            }

            It 'Preserves normal browser profile separation by omitting user-data-dir' {
                $Url = 'https://127.0.0.1:8765/tv'
                $Args = Get-BrowserLaunchArguments -Url $Url

                ($Args -contains $Url) | Should -Be $true
                ($Args -notcontains '--user-data-dir') | Should -Be $true
                ($Args -notcontains '--kiosk') | Should -Be $true
                (-not ($Args -match '--user-data-dir')) | Should -Be $true
                (-not ($Args -match '--kiosk')) | Should -Be $true
            }

            It 'uses the backend pairing URL rather than deriving a default route' {
                $PairingResponse = [PSCustomObject]@{ remote_url = 'https://192.168.1.44:8765/remote' }
                (Get-PairingRemoteUrl -PairingResponse $PairingResponse -Port 8765) |
                    Should -Be 'https://192.168.1.44:8765/remote'
                (Get-PairingRemoteUrl -PairingResponse ([PSCustomObject]@{}) -Port 9000) |
                    Should -Be 'http://<PC-LAN-IP>:9000/remote'
                (Get-PairingRemoteUrl -PairingResponse ([PSCustomObject]@{}) -Port 9000 -Scheme 'https') |
                    Should -Be 'https://<PC-LAN-IP>:9000/remote'
            }
        }

        Context 'Autostart Task Construction and Idempotent Removal' {
            It 'Builds scheduled task spec with hidden window, bypass policy, and AtLogOn trigger' {
                $ScriptPath = 'C:\freetv\scripts\start.ps1'
                $Spec = Get-AutostartTaskSpec -StartScriptPath $ScriptPath -TaskName 'PC TV Box'

                $Spec.TaskName | Should -Be 'PC TV Box'
                $Spec.Execute | Should -Be 'powershell.exe'
                $Spec.Argument | Should -Be '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\freetv\scripts\start.ps1"'
                $Spec.Description | Should -Be 'Starts the per-user PC TV Box controller after Windows sign-in.'
                $Spec.TriggerType | Should -Be 'AtLogOn'
                $Spec.StartWhenAvailable | Should -Be $true
                $Spec.ExecutionTimeLimitMinutes | Should -Be 5
            }

            It 'Supports idempotent task removal without error' {
                { Remove-AutostartTask -TaskName 'PC TV Box Test' } | Should -Not -Throw
            }
        }
    }

    $PesterModule = Get-Module -Name Pester | Select-Object -Last 1
    $FailedCount = 0
    if ($PesterModule) {
        $FailedCount = & $PesterModule {
            if (Get-Variable -Name pester -Scope Script -ErrorAction SilentlyContinue) {
                return [int]$script:pester.FailedCount
            } elseif (Get-Variable -Name pester -ErrorAction SilentlyContinue) {
                return [int]$pester.FailedCount
            }
            return 0
        }
    }
    if (-not $FailedCount -and (Get-Variable -Name pester -Scope Global -ErrorAction SilentlyContinue)) {
        $FailedCount = [int]$global:pester.FailedCount
    }
    if ($FailedCount -gt 0) {
        throw "$FailedCount Pester test(s) failed."
    }
} else {
    function Assert-Equal($Actual, $Expected, [string]$Message) {
        if ($Actual -ne $Expected) {
            throw "Assertion failed ($Message): expected '$Expected', got '$Actual'."
        }
    }

    function Assert-True($Condition, [string]$Message) {
        if (-not $Condition) {
            throw "Assertion failed ($Message): expected condition to be true."
        }
    }

    function Assert-Throws([scriptblock]$Block, [string]$Message) {
        $Threw = $false
        try {
            & $Block
        } catch {
            $Threw = $true
        }
        if (-not $Threw) {
            throw "Assertion failed ($Message): expected exception to be thrown."
        }
    }

    # 1. Missing applications section
    $Settings2 = '{"server":{"host":"0.0.0.0","port":9000},"applications":{"brave_path":"C:\\brave.exe"}}' | ConvertFrom-Json
    $Config2 = Get-StartupSettings -Settings $Settings2
    Assert-Equal $Config2.Port 9000 'Port extraction with missing edge_path'
    Assert-Equal $Config2.BindHost '0.0.0.0' 'BindHost extraction'
    Assert-Equal $Config2.HealthHost '127.0.0.1' 'HealthHost extraction with 0.0.0.0 host'
    Assert-Equal $Config2.ConfiguredEdgePath '' 'ConfiguredEdgePath defaults to empty when missing in applications'

    # 2. Missing edge_path in applications
    $Settings2 = '{"server":{"host":"127.0.0.1","port":9000},"applications":{"brave_path":"C:\\brave.exe"}}' | ConvertFrom-Json
    $Config2 = Get-StartupSettings -Settings $Settings2
    Assert-Equal $Config2.Port 9000 'Port extraction with missing edge_path'
    Assert-Equal $Config2.BindHost '127.0.0.1' 'BindHost extraction'
    Assert-Equal $Config2.HealthHost '127.0.0.1' 'HealthHost extraction with 127.0.0.1 host'
    Assert-Equal $Config2.ConfiguredEdgePath '' 'ConfiguredEdgePath defaults to empty when missing in applications'

    # 3. Configured edge_path present
    $Settings3 = '{"server":{"host":"0.0.0.0","port":8765},"applications":{"edge_path":"C:\\Custom\\msedge.exe"}}' | ConvertFrom-Json
    $Config3 = Get-StartupSettings -Settings $Settings3

    $UnsupportedHostSettings = '{"server":{"host":"127.0.0.1","port":8765}}' | ConvertFrom-Json
    Assert-Throws { Get-StartupSettings -Settings $UnsupportedHostSettings } 'Unsupported server host must throw'
    Assert-Equal $Config3.ConfiguredEdgePath 'C:\Custom\msedge.exe' 'Configured edge_path extraction'

    # 4. Invalid port / missing server
    $InvalidPortSettings = '{"server":{"host":"0.0.0.0","port":70000}}' | ConvertFrom-Json
    Assert-Throws { Get-StartupSettings -Settings $InvalidPortSettings } 'Invalid port must throw'

    $MissingServerSettings = '{"applications":{}}' | ConvertFrom-Json
    Assert-Throws { Get-StartupSettings -Settings $MissingServerSettings } 'Missing server must throw'

    # 5. Kiosk profile and URL args
    $Url = 'https://127.0.0.1:8765/tv'
    $UserDataDir = 'C:\TV Box\config\edge-profile'
    $KioskArgs = Get-EdgeKioskArguments -Url $Url -UserDataDir $UserDataDir
    Assert-True ($KioskArgs -contains '--kiosk') 'Kiosk args contains --kiosk'
    Assert-True ($KioskArgs -contains $Url) 'Kiosk args contains URL'
    Assert-True ($KioskArgs -contains '--edge-kiosk-type=fullscreen') 'Kiosk args contains --edge-kiosk-type=fullscreen'
    Assert-True ($KioskArgs -contains '--no-first-run') 'Kiosk args contains --no-first-run'
    Assert-True ($KioskArgs -contains '--user-data-dir="C:\TV Box\config\edge-profile"') 'Kiosk args quotes dedicated user-data-dir'

    # 6. User data directory path resolution
    $ResolvedDir = Get-EdgeUserDataDirectory -RootDirectory 'C:\freetv'
    Assert-Equal $ResolvedDir 'C:\freetv\config\edge-profile' 'Resolved kiosk profile directory'

    # 7. Normal browser profile separation by omission
    $BrowserArgs = Get-BrowserLaunchArguments -Url $Url
    Assert-True ($BrowserArgs -contains $Url) 'Browser args contains URL'
    Assert-True (-not ($BrowserArgs -match '--user-data-dir')) 'Browser args omits user-data-dir'
    Assert-True (-not ($BrowserArgs -match '--kiosk')) 'Browser args omits --kiosk'


    # 8. Pairing URL comes from the backend physical-LAN policy
    $PairingResponse = [PSCustomObject]@{ remote_url = 'https://192.168.1.44:8765/remote' }
    Assert-Equal (Get-PairingRemoteUrl -PairingResponse $PairingResponse -Port 8765) `
        'https://192.168.1.44:8765/remote' 'Backend pairing URL'
    Assert-Equal (Get-PairingRemoteUrl -PairingResponse ([PSCustomObject]@{}) -Port 9000) `
        'http://<PC-LAN-IP>:9000/remote' 'Missing pairing URL placeholder'
    Assert-Equal (Get-PairingRemoteUrl -PairingResponse ([PSCustomObject]@{}) -Port 9000 -Scheme 'https') `
        'https://<PC-LAN-IP>:9000/remote' 'Missing pairing URL placeholder with https scheme'
    # 8. Autostart task install spec
    $ScriptPath = 'C:\freetv\scripts\start.ps1'
    $Spec = Get-AutostartTaskSpec -StartScriptPath $ScriptPath -TaskName 'PC TV Box'
    Assert-Equal $Spec.TaskName 'PC TV Box' 'TaskName'
    Assert-Equal $Spec.Execute 'powershell.exe' 'Execute'
    Assert-Equal $Spec.Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\freetv\scripts\start.ps1"' 'Argument'
    Assert-Equal $Spec.Description 'Starts the per-user PC TV Box controller after Windows sign-in.' 'Description'
    Assert-Equal $Spec.TriggerType 'AtLogOn' 'TriggerType'
    Assert-True $Spec.StartWhenAvailable 'StartWhenAvailable'
    Assert-Equal $Spec.ExecutionTimeLimitMinutes 5 'ExecutionTimeLimitMinutes'

    # 9. Idempotent task removal
    Remove-AutostartTask -TaskName 'PC TV Box Nonexistent Test Task'
    Remove-AutostartTask -TaskName 'PC TV Box Nonexistent Test Task'

    Write-Host 'All startup unit tests passed successfully.'
}
