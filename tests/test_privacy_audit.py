import json
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import audit_privacy
from tools.audit_privacy import inspect_file


class PrivacyAuditTests(unittest.TestCase):
    def test_private_files_are_blocked_even_when_force_staged(self):
        for path in ('outputs/config/forms.json', 'backup/forms.json', 'browser-profile/Cookies',
                     'outputs/state/2026-10-02/state.json', 'backup/installation.json', '.env', 'identity.key'):
            self.assertEqual(inspect_file(path, b'{}'), ['private_file'])

    def test_identifying_data_and_secrets_return_codes_without_values(self):
        samples = [
            ('personal_windows_path', 'C:' + '/' + 'Users/' + 'fixture-person/private'),
            ('email_address', 'fictional-person' + '@' + 'example.invalid'),
            ('ssn_shape', '123' + '-45-' + '6789'),
            ('phone_shape', '(555)' + ' 123-4567'),
            ('secret_shape', 'ghp_' + 'A' * 40),
        ]
        for code, value in samples:
            result = inspect_file('notes.md', value.encode())
            self.assertIn(code, result)
            self.assertNotIn(value, json.dumps(result))

    def test_only_explicitly_synthetic_form_links_are_allowed(self):
        prefix = 'https://forms.office.com/r?id='
        self.assertIn('non_synthetic_form_link', inspect_file('notes.md', (prefix + 'not-a-demo').encode()))
        self.assertEqual(inspect_file('tests/example.py', (prefix + 'synthetic-demo').encode()), [])

    def run_staged_audit(self, folder):
        with patch.object(audit_privacy, 'ROOT', folder), contextlib.redirect_stdout(io.StringIO()) as output:
            code = audit_privacy.main(['--staged'])
        return code, json.loads(output.getvalue())

    def init_repo(self, folder):
        subprocess.run(['git', 'init', '-q', str(folder)], check=True, capture_output=True)

    def test_actual_staged_blob_is_checked_instead_of_working_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.init_repo(root)
            path = root / 'notes.md'
            path.write_text('fictional-person' + '@' + 'example.invalid')
            subprocess.run(['git', '-C', str(root), 'add', 'notes.md'], check=True, capture_output=True)
            path.write_text('Now harmless in the working copy')
            code, result = self.run_staged_audit(root)
            self.assertEqual(code, 1)
            self.assertEqual(result['findings'][0]['codes'], ['email_address'])

    def test_force_added_ignored_private_file_is_still_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.init_repo(root)
            (root / '.gitignore').write_text('config/\n')
            path = root / 'config' / 'forms.json'
            path.parent.mkdir()
            path.write_text('{"synthetic":true}')
            subprocess.run(['git', '-C', str(root), 'add', '-f', 'config/forms.json'], check=True, capture_output=True)
            code, result = self.run_staged_audit(root)
            self.assertEqual(code, 1)
            self.assertEqual(result['findings'][0]['codes'], ['private_file'])


if __name__ == '__main__':
    unittest.main()
