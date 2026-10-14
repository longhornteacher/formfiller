"""Bootstrap behavior with synthetic downloads/installers; no host installation."""
import os
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / 'tools' / 'Bootstrap-WebUI.ps1'


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        windows_shell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        self.shell = str(windows_shell) if windows_shell.exists() else shutil.which('pwsh')
        if not self.shell:
            self.skipTest('PowerShell required')
        self.temp = tempfile.TemporaryDirectory(prefix='formfiller-bootstrap-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_script(self, body):
        script = self.root / 'probe.ps1'
        script.write_text(
            ". '" + str(BOOTSTRAP).replace("'", "''") + "'\n"
            "$dependencyRoot = Join-Path $PSScriptRoot 'dependencies with spaces'\n" + body,
            encoding='utf-8-sig')
        result = subprocess.run([self.shell, '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(script)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_entrypoint_uses_builtin_shell(self):
        batch = (ROOT / 'LaunchWebUI.bat').read_text()
        self.assertIn('WindowsPowerShell\\v1.0\\powershell.exe', batch)
        self.assertIn('Bootstrap-WebUI.ps1', batch)
        self.assertNotIn('where pwsh', batch)

    def test_double_click_entrypoint_resolves_default_root_in_windows_powershell(self):
        if os.name != 'nt' or not shutil.which('pwsh'):
            self.skipTest('Windows and PowerShell 7 required for batch entrypoint')
        repo = self.root / 'synthetic repo with spaces'
        (repo / 'tools').mkdir(parents=True)
        shutil.copy(ROOT / 'LaunchWebUI.bat', repo / 'LaunchWebUI.bat')
        shell = shutil.which('pwsh').replace("'", "''")
        # Keep real -File entrypoint/default binding; isolate installers and UI.
        bootstrap = BOOTSTRAP.read_text().replace(
            '# Dot-sourcing exposes helpers',
            "function Resolve-FormFillerPowerShell { param($DependencyRoot) return '" + shell + "' }\n"
            "function Install-FormFillerEdge { }\n# Dot-sourcing exposes helpers")
        (repo / 'tools' / 'Bootstrap-WebUI.ps1').write_text(bootstrap, encoding='utf-8-sig')
        (repo / 'tools' / 'Launch-WebUI.ps1').write_text(
            "param($RepositoryRoot,$AppDataRoot)\n"
            "[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'launched.json'), "
            "(@{root=[IO.Path]::GetFullPath($RepositoryRoot)} | ConvertTo-Json))\nexit 0\n",
            encoding='utf-8-sig')
        result = subprocess.run(['cmd.exe', '/d', '/c', str(repo / 'LaunchWebUI.bat')],
                                cwd=self.root, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        launched = json.loads((repo / 'tools' / 'launched.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(Path(launched['root']).resolve(), repo.resolve())

    def test_hash_mismatch_stops_before_execution(self):
        result = self.run_script("""
function Invoke-WebRequest { param([switch]$UseBasicParsing,$Uri,$OutFile) [IO.File]::WriteAllText($OutFile,'synthetic payload') }
try { Receive-VerifiedDependency 'https://example.org/fixture' (Join-Path $PSScriptRoot 'fixture.zip') ('0' * 64); throw 'accepted invalid download' }
catch { if ($_.Exception.Message -ne 'dependency_download_invalid') { throw }; Write-Output 'REJECTED' }
""")
        self.assertIn('REJECTED', result)

    def test_matching_hash_accepts_download(self):
        result = self.run_script("""
function Invoke-WebRequest { param([switch]$UseBasicParsing,$Uri,$OutFile) [IO.File]::WriteAllText($OutFile,'synthetic payload') }
$hash = [Security.Cryptography.SHA256]::Create()
try { $expected = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes('synthetic payload'))).Replace('-','') }
finally { $hash.Dispose() }
Receive-VerifiedDependency 'https://example.org/fixture' (Join-Path $PSScriptRoot 'fixture.zip') $expected
Write-Output 'ACCEPTED'
""")
        self.assertIn('ACCEPTED', result)

    def test_cached_python_requires_no_download(self):
        result = self.run_script("""
function Test-FormFillerPython { param($Executable) return $true }
function Receive-VerifiedDependency { throw 'unexpected download' }
Resolve-FormFillerPython $dependencyRoot
""")
        self.assertIn('Python313', result)

    def test_missing_python_installs_per_user_and_validates(self):
        result = self.run_script("""
$script:installed = $false
function Test-FormFillerPython { param($Executable) return $script:installed }
function Get-Command { param($Name,$ErrorAction) return $null }
function Receive-VerifiedDependency { param($Url,$Destination,$Hash)
    if ($Url -notlike 'https://www.python.org/*' -or $Hash.Length -ne 64) { throw 'invalid source' }
}
function Start-Process { param($FilePath,$ArgumentList,[switch]$Wait,[switch]$PassThru,$WindowStyle)
    if ($ArgumentList -notcontains 'InstallAllUsers=0' -or $ArgumentList -notcontains 'Include_tcltk=1' -or $WindowStyle -ne 'Hidden') { throw 'invalid install options' }
    $script:installed = $true
    return @{ExitCode=0}
}
$resolved = Resolve-FormFillerPython $dependencyRoot
if (-not $resolved.EndsWith('Python313\\python.exe')) { throw 'invalid resolved path' }
Write-Output 'INSTALLED'
""")
        self.assertIn('INSTALLED', result)

    def test_failed_python_install_stops(self):
        result = self.run_script("""
function Test-FormFillerPython { param($Executable) return $false }
function Get-Command { param($Name,$ErrorAction) return $null }
function Receive-VerifiedDependency { param($Url,$Destination,$Hash) }
function Start-Process { param($FilePath,$ArgumentList,[switch]$Wait,[switch]$PassThru,$WindowStyle) return @{ExitCode=1603} }
try { Resolve-FormFillerPython $dependencyRoot; throw 'accepted failed installer' }
catch { if ($_.Exception.Message -ne 'python_install_failed') { throw }; Write-Output 'STOPPED' }
""")
        self.assertIn('STOPPED', result)

    def test_missing_powershell_downloads_and_verifies_before_execution(self):
        result = self.run_script("""
function Get-Command { param($Name,$ErrorAction) return $null }
function Receive-VerifiedDependency { param($Url,$Destination,$Hash)
    if ($Url -notlike 'https://github.com/PowerShell/PowerShell/*' -or $Hash.Length -ne 64) { throw 'invalid source' }
    Write-Output 'VERIFIED'
}
function Expand-Archive { param($LiteralPath,$DestinationPath)
    New-Item -ItemType Directory -Path $DestinationPath | Out-Null
    # A harmless command stub exercises launching after extraction.
    [IO.File]::WriteAllText((Join-Path $DestinationPath 'pwsh.cmd'), "@exit /b 0`r`n")
    [IO.File]::WriteAllText((Join-Path $DestinationPath 'pwsh.exe'), 'synthetic')
}
function Get-AuthenticodeSignature { param($LiteralPath)
    return @{Status='Invalid';SignerCertificate=@{Subject='O=Microsoft Corporation'}}
}
try { Resolve-FormFillerPowerShell $dependencyRoot; throw 'accepted invalid signature' }
catch { if ($_.Exception.Message -ne 'dependency_signature_invalid') { throw }; Write-Output 'REJECTED' }
""")
        self.assertIn('VERIFIED', result)
        self.assertIn('REJECTED', result)

    def test_existing_edge_does_not_install(self):
        result = self.run_script("""
function Test-FormFillerEdge { return $true }
function Get-Command { throw 'unexpected package manager lookup' }
Install-FormFillerEdge
Write-Output 'REUSED'
""")
        self.assertIn('REUSED', result)

    def test_missing_edge_without_package_manager_stops(self):
        result = self.run_script("""
function Test-FormFillerEdge { return $false }
function Get-Command { param($Name,$ErrorAction) return $null }
try { Install-FormFillerEdge; throw 'ignored missing Edge' }
catch { if ($_.Exception.Message -ne 'edge_install_requires_it') { throw }; Write-Output 'STOPPED' }
""")
        self.assertIn('STOPPED', result)

    def test_missing_edge_installs_and_rechecks(self):
        result = self.run_script("""
$script:checks = 0
function Test-FormFillerEdge { $script:checks += 1; return ($script:checks -gt 1) }
$script:fixtureWinget = Join-Path $PSScriptRoot 'winget.cmd'
[IO.File]::WriteAllText($script:fixtureWinget, "@echo %*`r`n@exit /b 0`r`n")
function Get-Command { param($Name,$ErrorAction) return @{Source=$script:fixtureWinget} }
Install-FormFillerEdge
if ($script:checks -ne 2) { throw 'Edge installation not verified' }
""")
        self.assertIn('--id Microsoft.Edge --exact --source winget', result)


if __name__ == '__main__':
    unittest.main()
