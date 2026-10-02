import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'tools' / 'Launch-WebUI.ps1'
STUB_UI = """param([Parameter(ValueFromRemainingArguments=$true)][string[]]$WebArgs)
ConvertTo-Json -InputObject @($WebArgs) | Set-Content (Join-Path $PSScriptRoot 'launched.json')
exit 0
"""


class WebUILauncherTests(unittest.TestCase):
    def setUp(self):
        self.shell = shutil.which('pwsh')
        if not self.shell:
            self.skipTest('PowerShell 7 is required')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo with spaces'
        (self.repo / 'tools').mkdir(parents=True)
        self.local = self.root / 'local'
        self.app = self.local / 'FormFiller'
        self.app.mkdir(parents=True)

    def launch(self):
        return subprocess.run([self.shell, '-NoProfile', '-File', str(LAUNCHER),
            '-RepositoryRoot', str(self.repo), '-AppDataRoot', str(self.local)],
            capture_output=True, text=True, timeout=30)

    def test_existing_install_opens_webui_without_build_or_submission(self):
        installed = self.root / 'installed'
        installed.mkdir()
        (installed / 'Run-FormFillerPrivate.ps1').write_text(STUB_UI)
        (self.app / 'paths.json').write_text(json.dumps({'installed_app': str(installed)}))
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads((installed / 'launched.json').read_text(encoding='utf-8-sig')), ['--open'])
        self.assertNotIn('first use', result.stdout)

    def test_first_launch_bootstraps_then_opens_installed_ui(self):
        (self.repo / 'tools' / 'Build-CleanSource.ps1').write_text("""param($RepositoryRoot,$OutputRoot)
New-Item -ItemType Directory -Path (Join-Path $OutputRoot 'formfiller-clean-source') -Force | Out-Null
""")
        (self.repo / 'tools' / 'Install-ReviewedSnapshot.ps1').write_text("""param($Destination,$SourceRoot,$SourceBundle,[switch]$InstallDependencies)
if (-not $InstallDependencies) { throw 'fixture dependencies missing' }
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
@'
""" + STUB_UI + """'@ | Set-Content (Join-Path $Destination 'Run-FormFillerPrivate.ps1')
""")
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = list((self.app / 'App').glob('snapshot-ui-*'))
        self.assertEqual(len(installed), 1)
        self.assertEqual(json.loads((installed[0] / 'launched.json').read_text(encoding='utf-8-sig')), ['--open'])
        self.assertFalse((self.app / 'paths.json').exists())

    def test_invalid_existing_install_never_reinstalls_or_exposes_path(self):
        (self.app / 'paths.json').write_text(json.dumps({'installed_app': str(self.root / 'missing')}))
        result = self.launch()
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        self.assertFalse((self.app / 'App').exists())


if __name__ == '__main__':
    unittest.main()
