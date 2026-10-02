import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from outputs.formfiller import migrate
from outputs.formfiller.ownership import verify_runtime_owner


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.workspace, self.runtime = [self.root / name for name in ('source', 'workspace', 'runtime')]
        config = self.source / 'outputs' / 'config'
        config.mkdir(parents=True)
        (config / 'forms.json').write_text(json.dumps({'forms': [{'alias': 'F01', 'url': 'synthetic'}]}))
        (config / 'settings.json').write_text('{"live_enabled":false}')
        profile = config / 'browser-profile'
        profile.mkdir()
        (profile / 'fixture').write_bytes(b'synthetic browser profile')
        state = self.source / 'outputs' / 'state' / '2026-10-02'
        state.mkdir(parents=True)
        (state / 'state.json').write_bytes(b'{"date":"2026-10-02","forms":{"F01":{"status":"submitted"}}}')
        workbook = self.source / 'Pearland_2026-27_Instructional_Dates_Full_Text.xlsx'
        workbook.write_bytes(b'synthetic workbook bytes')
        self.calendar = {'source_kind': 'district_workbook', 'workbook_path': str(workbook),
                         'workbook_sha256': 'unchanged even if source differs', 'approved': True,
                         'exported_at_utc': '2026-10-01T12:00:00Z', 'school_days': ['2026-10-02']}
        (config / 'calendar.json').write_text(json.dumps(self.calendar))
        (self.source / 'Accommodation Log.txt').write_bytes(b'synthetic example only')
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'local')}).start()

    def test_preserves_identity_state_profile_and_calendar_provenance(self):
        state_before = migrate.fingerprints(self.source / 'outputs' / 'state')
        forms_before = (self.source / 'outputs' / 'config' / 'forms.json').read_bytes()
        profile_before = migrate.fingerprints(self.source / 'outputs' / 'config' / 'browser-profile')
        result = migrate.migrate(self.source, self.workspace, self.runtime)
        self.assertGreater(result['files'], 0)
        self.assertEqual(migrate.fingerprints(self.runtime / 'state'), state_before)
        self.assertEqual(migrate.fingerprints(self.runtime / 'browser-profile'), profile_before)
        self.assertEqual((self.workspace / 'config' / 'forms.json').read_bytes(), forms_before)
        updated = json.loads((self.workspace / 'config' / 'calendar.json').read_bytes())
        self.assertEqual(updated.pop('workbook_path'), str(self.workspace / 'sources' / Path(self.calendar['workbook_path']).name))
        self.assertEqual(updated, {k: v for k, v in self.calendar.items() if k != 'workbook_path'})
        self.assertFalse((self.source / 'outputs' / 'config').exists())
        verify_runtime_owner(self.workspace, self.runtime)

    def test_failed_locator_write_rolls_back_files_calendar_and_new_pair(self):
        before = migrate.fingerprints(self.source)
        original = migrate._atomic_json
        def fail_locator(path, value):
            if path.name == 'paths.json':
                raise OSError('synthetic failure')
            original(path, value)
        with patch.object(migrate, '_atomic_json', side_effect=fail_locator):
            with self.assertRaisesRegex(migrate.MigrationError, '^migration_failed_rolled_back$'):
                migrate.migrate(self.source, self.workspace, self.runtime)
        self.assertEqual(migrate.fingerprints(self.source), before)
        self.assertFalse((self.workspace / '.formfiller-owner.json').exists())
        self.assertFalse((self.runtime / '.formfiller-owner.json').exists())

    def test_conflicting_destination_and_locked_runner_leave_source_untouched(self):
        before = migrate.fingerprints(self.source)
        target = self.workspace / 'config'
        target.mkdir(parents=True)
        with self.assertRaisesRegex(migrate.MigrationError, '^migration_destination_conflict$'):
            migrate.migrate(self.source, self.workspace, self.runtime)
        self.assertEqual(migrate.fingerprints(self.source), before)
        state = self.source / 'outputs' / 'state'
        (state / '.runner.lock').write_text('synthetic')
        with self.assertRaisesRegex(migrate.MigrationError, '^run_locked$'):
            migrate.migrate(self.source, self.workspace, self.runtime)

    def test_existing_owner_is_never_rebound(self):
        self.workspace.mkdir()
        marker = self.workspace / '.formfiller-owner.json'
        marker.write_text('{"owner_id":"existing"}')
        before = migrate.fingerprints(self.source)
        with self.assertRaisesRegex(migrate.MigrationError, '^runtime_owner_exists$'):
            migrate.migrate(self.source, self.workspace, self.runtime)
        self.assertEqual(migrate.fingerprints(self.source), before)
        self.assertEqual(marker.read_text(), '{"owner_id":"existing"}')

    def test_absolute_legacy_calendar_location_is_relocated_without_other_settings_changes(self):
        config = self.source / 'outputs' / 'config'
        settings = {'live_enabled': False, 'calendar_path': str(config / 'calendar.json'), 'max_calendar_age_days': 14}
        (config / 'settings.json').write_text(json.dumps(settings))
        migrate.migrate(self.source, self.workspace, self.runtime)
        settings['calendar_path'] = 'calendar.json'
        self.assertEqual(json.loads((self.workspace / 'config' / 'settings.json').read_bytes()), settings)

    def test_prior_locator_is_never_overwritten_and_gate_is_released(self):
        locator = self.root / 'local' / 'FormFiller' / 'paths.json'
        locator.parent.mkdir(parents=True)
        locator.write_bytes(b'synthetic existing locator')
        before = migrate.fingerprints(self.source)
        with self.assertRaisesRegex(migrate.MigrationError, '^workspace_locator_exists$'):
            migrate.migrate(self.source, self.workspace, self.runtime)
        self.assertEqual(migrate.fingerprints(self.source), before)
        self.assertEqual(locator.read_bytes(), b'synthetic existing locator')

    def test_prior_migration_gate_is_never_removed(self):
        gate = self.source / 'outputs' / '.migration.lock'
        gate.write_bytes(b'synthetic existing gate')
        with self.assertRaisesRegex(migrate.MigrationError, '^migration_in_progress$'):
            migrate.migrate(self.source, self.workspace, self.runtime)
        self.assertEqual(gate.read_bytes(), b'synthetic existing gate')


if __name__ == '__main__':
    unittest.main()
