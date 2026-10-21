"""Validate scheduler first-use setup with -WhatIf; never register a task."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ScheduleInstallTests(unittest.TestCase):
    def setUp(self):
        self.shell = shutil.which('pwsh')
        if sys.platform != 'win32' or not self.shell:
            self.skipTest('Windows and PowerShell 7 required')
        self.temp = tempfile.TemporaryDirectory(prefix='formfiller-schedule-install-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.local = self.root / 'local'
        self.app = self.local / 'FormFiller'
        self.snapshot = self.app / 'snapshot'
        self.snapshot.mkdir(parents=True)
        package = self.snapshot / 'formfiller'
        package.mkdir()
        for source in (ROOT / 'outputs/formfiller').glob('*.py'):
            shutil.copyfile(source, package / source.name)
        # The test supplies only source and a private-free manifest.
        files = {str(p.relative_to(self.snapshot).as_posix()): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in package.iterdir() if p.is_file()}
        (self.snapshot / 'install-manifest.json').write_text(json.dumps({
            'version': 1, 'source_root': str(ROOT), 'files': files}))
        (self.snapshot / 'Run-FormFillerOperation.ps1').write_text("throw 'synthetic_operation_must_not_execute'\n")
        subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(self.snapshot / '.venv')],
                       check=True, capture_output=True, timeout=30)
        (self.app / 'installation.json').write_text(json.dumps({'version': 1, 'installed_app': str(self.snapshot)}))

    def invoke(self, allow=True):
        env = os.environ.copy()
        env.update({'LOCALAPPDATA': str(self.local), 'FORM_FILLER_WORKSPACE': '',
                    'FORM_FILLER_RUNTIME': '', 'FORM_FILLER_INSTALLED_APP': '',
                    'PYTHONPATH': os.pathsep.join(path for path in sys.path if 'site-packages' in path)})
        command = [self.shell, '-NoProfile', '-File', str(ROOT / 'tools/Install-SchoolDaySchedule.ps1'),
                   '-Snapshot', str(self.snapshot), '-TaskName', 'FormFiller Synthetic Installer Test', '-WhatIf']
        if allow:
            command.append('-AllowUnconfigured')
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)

    def test_unconfigured_install_validates_without_binding_or_running(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('What if:', result.stdout)
        self.assertFalse((self.app / 'paths.json').exists())
        self.assertFalse((self.app / 'runtime').exists())

    def test_standalone_schedule_install_requires_existing_owner(self):
        self.assertNotEqual(self.invoke(allow=False).returncode, 0)
        self.assertFalse((self.app / 'paths.json').exists())

    def test_changed_snapshot_is_not_accepted_for_first_use(self):
        (self.snapshot / 'formfiller/__init__.py').write_text('# changed synthetic module\n')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('install_hash_mismatch', result.stdout)
