Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

BeforeAll {
    $ScriptPath = Join-Path $PSScriptRoot '..\build-offline-bundle.ps1'
    . $ScriptPath

    function Get-TestDigest {
        param([byte[]]$Bytes)

        $Sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            return ([System.BitConverter]::ToString($Sha256.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
        }
        finally {
            $Sha256.Dispose()
        }
    }
}

Describe 'Offline bundle artifact verification' {
    BeforeEach {
        $Destination = Join-Path $TestDrive 'artifact.bin'
    }

    It 'downloads a missing artifact from its pinned URL and accepts exact bytes' {
        $Bytes = [System.Text.Encoding]::ASCII.GetBytes('trusted-artifact')
        $Component = [pscustomobject]@{
            url = 'https://www.python.org/pinned/artifact.bin'
            size = $Bytes.Length
            sha256 = Get-TestDigest -Bytes $Bytes
        }
        Mock Invoke-ArtifactRequest {
            param($Uri, $Destination)
            [System.IO.File]::WriteAllBytes($Destination, $Bytes)
            [pscustomobject]@{ StatusCode = 200; Location = $null }
        }

        Get-VerifiedArtifact -Component $Component -Destination $Destination

        [System.IO.File]::ReadAllBytes($Destination) | Should -Be $Bytes
        Should -Invoke Invoke-ArtifactRequest -Times 1 -Exactly -ParameterFilter {
            [string]$Uri -eq $Component.url
        }
    }

    It 'replaces a corrupt cached file only from the same pinned URL' {
        $Bytes = [System.Text.Encoding]::ASCII.GetBytes('trusted-artifact')
        [System.IO.File]::WriteAllText($Destination, 'corrupt')
        $Component = [pscustomobject]@{
            url = 'https://github.com/example/releases/download/v1/artifact.bin'
            size = $Bytes.Length
            sha256 = Get-TestDigest -Bytes $Bytes
        }
        Mock Invoke-ArtifactRequest {
            param($Uri, $Destination)
            [System.IO.File]::WriteAllBytes($Destination, $Bytes)
            [pscustomobject]@{ StatusCode = 200; Location = $null }
        }

        Get-VerifiedArtifact -Component $Component -Destination $Destination

        [System.IO.File]::ReadAllBytes($Destination) | Should -Be $Bytes
        Should -Invoke Invoke-ArtifactRequest -Times 1 -Exactly -ParameterFilter {
            [string]$Uri -eq $Component.url
        }
    }

    It 'rejects corrupt downloaded bytes before they can be extracted' {
        $ExpectedBytes = [System.Text.Encoding]::ASCII.GetBytes('good')
        $CorruptBytes = [System.Text.Encoding]::ASCII.GetBytes('evil')
        $Component = [pscustomobject]@{
            url = 'https://github.com/example/releases/download/v1/artifact.bin'
            size = $ExpectedBytes.Length
            sha256 = Get-TestDigest -Bytes $ExpectedBytes
        }
        Mock Invoke-ArtifactRequest {
            param($Uri, $Destination)
            [System.IO.File]::WriteAllBytes($Destination, $CorruptBytes)
            [pscustomobject]@{ StatusCode = 200; Location = $null }
        }

        { Get-VerifiedArtifact -Component $Component -Destination $Destination } |
            Should -Throw 'Artifact SHA-256 mismatch*'
    }

    It 'rejects a truncated download before it can be extracted' {
        $ExpectedBytes = [System.Text.Encoding]::ASCII.GetBytes('complete')
        $TruncatedBytes = [System.Text.Encoding]::ASCII.GetBytes('short')
        $Component = [pscustomobject]@{
            url = 'https://release-assets.githubusercontent.com/pinned/artifact.bin'
            size = $ExpectedBytes.Length
            sha256 = Get-TestDigest -Bytes $ExpectedBytes
        }
        Mock Invoke-ArtifactRequest {
            param($Uri, $Destination)
            [System.IO.File]::WriteAllBytes($Destination, $TruncatedBytes)
            [pscustomobject]@{ StatusCode = 200; Location = $null }
        }

        { Get-VerifiedArtifact -Component $Component -Destination $Destination } |
            Should -Throw 'Artifact size mismatch*'
    }

    It 'resolves an approved relative redirect before downloading' {
        $Bytes = [System.Text.Encoding]::ASCII.GetBytes('trusted-artifact')
        $Component = [pscustomobject]@{
            url = 'https://github.com/example/releases/download/v1/artifact.bin'
            size = $Bytes.Length
            sha256 = Get-TestDigest -Bytes $Bytes
        }
        $RequestUris = [System.Collections.Generic.List[string]]::new()
        Mock Invoke-ArtifactRequest {
            param($Uri, $Destination)
            $RequestUris.Add([string]$Uri)
            if ($RequestUris.Count -eq 1) {
                return [pscustomobject]@{
                    StatusCode = 302
                    Location = '/trusted/artifact.bin'
                }
            }
            [System.IO.File]::WriteAllBytes($Destination, $Bytes)
            [pscustomobject]@{ StatusCode = 200; Location = $null }
        }

        Get-VerifiedArtifact -Component $Component -Destination $Destination

        $RequestUris | Should -Be @(
            'https://github.com/example/releases/download/v1/artifact.bin',
            'https://github.com/trusted/artifact.bin'
        )
        [System.IO.File]::ReadAllBytes($Destination) | Should -Be $Bytes
    }

    It 'rejects an unapproved redirect target before following it' {
        $Component = [pscustomobject]@{
            url = 'https://github.com/example/releases/download/v1/artifact.bin'
            size = 1
            sha256 = ('0' * 64)
        }
        Mock Invoke-ArtifactRequest {
            [pscustomobject]@{
                StatusCode = 302
                Location = 'https://example.com/payload.bin'
            }
        }

        { Get-VerifiedArtifact -Component $Component -Destination $Destination } |
            Should -Throw 'Artifact URL host is not approved*'
        Should -Invoke Invoke-ArtifactRequest -Times 1 -Exactly
        Test-Path -LiteralPath $Destination | Should -BeFalse
    }

    It 'stops after five approved redirects' {
        $Component = [pscustomobject]@{
            url = 'https://github.com/example/releases/download/v1/artifact.bin'
            size = 1
            sha256 = ('0' * 64)
        }
        Mock Invoke-ArtifactRequest {
            [pscustomobject]@{
                StatusCode = 302
                Location = '/redirect-loop'
            }
        }

        { Get-VerifiedArtifact -Component $Component -Destination $Destination } |
            Should -Throw 'Artifact redirect limit exceeded*'
        Should -Invoke Invoke-ArtifactRequest -Times 6 -Exactly
        Test-Path -LiteralPath $Destination | Should -BeFalse
    }

    It 'rejects an unapproved source without making a request' {
        $Component = [pscustomobject]@{
            url = 'https://example.com/artifact.bin'
            size = 1
            sha256 = ('0' * 64)
        }
        Mock Invoke-ArtifactRequest { throw 'must not be called' }

        { Get-VerifiedArtifact -Component $Component -Destination $Destination } |
            Should -Throw 'Artifact URL host is not approved*'
        Should -Invoke Invoke-ArtifactRequest -Times 0 -Exactly
    }
}
