"""Exercise installation in disposable app-data and Desktop folders only."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.shell = shutil.which('pwsh')
        if sys.platform != 'win32' or not self.shell:
            self.skipTest('Windows and PowerShell 7 required for shortcut tests')
        self.temp = tempfile.TemporaryDirectory(prefix='formfiller-install-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'source with spaces'
        self.tools = self.repo / 'tools'
        self.tools.mkdir(parents=True)
        self.local = self.root / 'app data'
        self.app = self.local / 'FormFiller'
        self.desktop = self.root / 'redirected desktop'
        for name in ('Install-FormFiller.ps1', 'Open-FormFiller.ps1', 'Build-LauncherIcon.ps1'):
            shutil.copyfile(ROOT / 'tools' / name, self.tools / name)
        assets = self.repo / 'outputs/formfiller/web_static'
        assets.mkdir(parents=True)
        shutil.copyfile(ROOT / 'outputs/formfiller/web_static/formfiller.svg', assets / 'formfiller.svg')
        shutil.copyfile(ROOT / 'outputs/formfiller/deployment.py', self.tools / 'deployment.py')
        (self.tools / 'Build-CleanSource.ps1').write_text('''param($RepositoryRoot,$OutputRoot)
New-Item -ItemType Directory -Path (Join-Path $OutputRoot 'formfiller-clean-source') -Force | Out-Null
''')
        (self.tools / 'Install-ReviewedSnapshot.ps1').write_text('''param($Destination,$SourceRoot,$SourceBundle,$PythonPath,[switch]$InstallDependencies)
if (-not $InstallDependencies) { throw 'dependencies_not_requested' }
New-Item -ItemType Directory -Path (Join-Path $Destination 'formfiller') -Force | Out-Null
& $PythonPath -m venv --without-pip (Join-Path $Destination '.venv')
if ($LASTEXITCODE -ne 0) { throw 'test_venv_failed' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'deployment.py') -Destination (Join-Path $Destination 'formfiller/deployment.py')
[IO.File]::WriteAllText((Join-Path $Destination 'formfiller/__init__.py'), '')
$files = @{}
foreach ($name in @('__init__.py','deployment.py')) {
    $files['formfiller/' + $name] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Destination ('formfiller/' + $name))).Hash.ToLowerInvariant()
}
@{version=1;source_root=$SourceRoot;files=$files} | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Destination 'install-manifest.json') -Encoding utf8NoBOM
@'
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$WebArgs)
@{arguments=@($WebArgs);local=$env:LOCALAPPDATA;workspace=$env:FORM_FILLER_WORKSPACE;runtime=$env:FORM_FILLER_RUNTIME} | ConvertTo-Json | Set-Content (Join-Path $PSScriptRoot 'launched.json')
exit 0
'@ | Set-Content (Join-Path $Destination 'Run-FormFillerPrivate.ps1')
''')
        # No task registration or live runner is available to these tests.
        (self.tools / 'Install-SchoolDaySchedule.ps1').write_text('''param($Snapshot,[switch]$AllowUnconfigured)
@{snapshot=$Snapshot;allow_unconfigured=$AllowUnconfigured.IsPresent;local=$env:LOCALAPPDATA;workspace=$env:FORM_FILLER_WORKSPACE} | ConvertTo-Json | Set-Content (Join-Path $Snapshot 'schedule-test.json')
''')

    def command(self, script, *args):
        return subprocess.run([self.shell, '-NoProfile', '-File', str(script), *map(str, args)],
                              capture_output=True, text=True, timeout=60)

    def install(self):
        return self.command(self.tools / 'Install-FormFiller.ps1', '-RepositoryRoot', self.repo,
                            '-AppDataRoot', self.local, '-DesktopDirectory', self.desktop,
                            '-PythonPath', sys.executable, '-NoLaunch')

    def installed(self):
        return Path(json.loads((self.app / 'installation.json').read_text())['installed_app'])

    def test_complete_install_shortcut_and_relaunch_without_clone(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('status=installed', result.stdout)
        installed = self.installed()
        self.assertTrue((self.desktop / 'Launch FormFiller.lnk').is_file())
        self.assertEqual((self.app / 'FormFiller.ico').read_bytes()[:6], b'\x00\x00\x01\x00\x07\x00')
        self.assertFalse((self.app / 'paths.json').exists())
        self.assertFalse((installed / 'launched.json').exists())
        scheduled = json.loads((installed / 'schedule-test.json').read_text(encoding='utf-8-sig'))
        self.assertTrue(scheduled['allow_unconfigured'])
        self.assertEqual(scheduled['local'], str(self.local))
        self.assertFalse(scheduled['workspace'])
        inspect = self.root / 'read-shortcut.ps1'
        inspect.write_text('''param($Shortcut)
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)
@{target=$link.TargetPath;arguments=$link.Arguments;directory=$link.WorkingDirectory;icon=$link.IconLocation} | ConvertTo-Json
''')
        shortcut = json.loads(self.command(inspect, self.desktop / 'Launch FormFiller.lnk').stdout)
        self.assertEqual(shortcut['icon'], str(self.app / 'FormFiller.ico') + ',0')
        self.assertIn('Open-FormFiller.ps1', shortcut['arguments'])
        self.assertIn('-WindowStyle Hidden', shortcut['arguments'])
        self.assertNotIn(str(self.repo), json.dumps(shortcut))
        self.assertEqual(shortcut['directory'], str(self.app))
        moved = self.root / 'moved source'
        self.repo.rename(moved)
        opened = self.command(self.app / 'Open-FormFiller.ps1', '-Foreground')
        self.assertEqual(opened.returncode, 0, opened.stdout + opened.stderr)
        receipt = json.loads((installed / 'launched.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(receipt['arguments'], ['--open'])
        self.assertEqual(receipt['local'], str(self.local))
        self.assertFalse(receipt['workspace'])

    def test_repeat_setup_reuses_unfinished_installation(self):
        self.assertEqual(self.install().returncode, 0)
        installed = self.installed()
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.installed(), installed)
        self.assertEqual(len(list((self.app / 'App').iterdir())), 1)

    def test_existing_workspace_and_submission_state_remain_identical(self):
        self.assertEqual(self.install().returncode, 0)
        private = self.root / 'private'
        runtime = self.root / 'runtime'
        private.mkdir()
        runtime.mkdir()
        (runtime / 'synthetic-state.txt').write_text('SYNTHETIC_STATE_SENTINEL')
        locator = self.app / 'paths.json'
        locator.write_text(json.dumps({'workspace': str(private), 'runtime': str(runtime), 'installed_app': str(self.installed())}))
        before = locator.read_bytes()
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(locator.read_bytes(), before)
        self.assertEqual((runtime / 'synthetic-state.txt').read_text(), 'SYNTHETIC_STATE_SENTINEL')

    def test_corrupt_snapshot_is_not_replaced_or_registered(self):
        self.assertEqual(self.install().returncode, 0)
        installed = self.installed()
        (installed / 'formfiller/__init__.py').write_text('# changed synthetic module\n')
        (installed / 'schedule-test.json').unlink()
        result = self.install()
        self.assertEqual(result.returncode, 2)
        self.assertIn('installed_snapshot_invalid', result.stdout)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        self.assertEqual(len(list((self.app / 'App').iterdir())), 1)
        self.assertFalse((installed / 'schedule-test.json').exists())

    def test_unrelated_desktop_shortcut_is_preserved(self):
        self.desktop.mkdir()
        path = self.desktop / 'Launch FormFiller.lnk'
        path.write_bytes(b'SYNTHETIC_UNRELATED_SHORTCUT')
        before = path.read_bytes()
        result = self.install()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.app / 'App').exists())

    def test_repeat_install_renames_owned_legacy_shortcut(self):
        self.assertEqual(self.install().returncode, 0)
        current = self.desktop / 'Launch FormFiller.lnk'
        legacy = self.desktop / 'FormFiller.lnk'
        current.rename(legacy)
        self.assertEqual(self.install().returncode, 0)
        self.assertTrue(current.is_file())
        self.assertFalse(legacy.exists())
