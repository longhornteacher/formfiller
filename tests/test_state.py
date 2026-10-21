import tempfile
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path

from outputs.formfiller.state import StateError, StateStore
from outputs.formfiller import state


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.temp.name), date(2026, 10, 1))

    def tearDown(self):
        self.temp.cleanup()

    def test_atomic_date_scoped_transitions_and_terminal_states(self):
        digest = "a" * 64
        self.assertEqual(self.store.bind_config("F01", digest)["status"], "pending")
        self.store.transition("F01", "pending", "submitting")
        self.store.transition("F01", "submitting", "submitted")
        with self.assertRaises(StateError):
            self.store.transition("F01", "submitted", "pending")
        self.assertEqual(self.store.read("F01")["status"], "submitted")
        self.assertTrue((Path(self.temp.name) / "2026-10-01" / "state.json").exists())

    def test_uncertain_state_cannot_be_reopened(self):
        self.store.bind_config("F02", "b" * 64)
        self.store.transition("F02", "pending", "submitting")
        self.store.transition("F02", "submitting", "uncertain", "outcome_uncertain")
        with self.assertRaises(StateError):
            self.store.transition("F02", "uncertain", "submitting")

    def test_changed_config_cannot_reopen_pending_or_failed_alias(self):
        self.store.bind_config("F03", "c" * 64)
        with self.assertRaises(StateError):
            self.store.bind_config("F03", "d" * 64)
        self.store.transition("F03", "pending", "failed", "browser_error")
        with self.assertRaises(StateError):
            self.store.bind_config("F03", "d" * 64)

    def test_exclusive_lock_fails_closed(self):
        with self.store.lock():
            with self.assertRaises(StateError) as caught:
                with self.store.lock():
                    pass
        self.assertEqual(caught.exception.code, "lock_exists")

    def test_schema_approval_binds_capture_and_config(self):
        schema, config = "e" * 64, "f" * 64
        self.store.record_schema("F04", schema)
        self.store.record_schema("F04", schema, approved=True, config_fingerprint=config)
        self.assertTrue(self.store.schema_approved("F04", schema, config))
        self.assertFalse(self.store.schema_approved("F04", schema, "0" * 64))

    def test_transient_windows_sharing_violation_retries_only_atomic_replace(self):
        error = PermissionError('synthetic sharing violation')
        error.winerror = 32
        with patch.object(state.os, 'name', 'nt'), patch.object(state.os, 'replace', side_effect=[error, None]) as replace, patch.object(state.time, 'sleep') as sleep:
            state._atomic_replace('synthetic-temp', 'synthetic-target')
        self.assertEqual(replace.call_count, 2)
        self.assertEqual(replace.call_args_list[0], replace.call_args_list[1])
        sleep.assert_called_once_with(0.02)

    def test_persistent_windows_sharing_violation_stops_after_bounded_attempts(self):
        error = PermissionError('synthetic access denied')
        error.winerror = 5
        with patch.object(state.os, 'name', 'nt'), patch.object(state.os, 'replace', side_effect=error) as replace, patch.object(state.time, 'sleep'):
            with self.assertRaises(PermissionError):
                state._atomic_replace('synthetic-temp', 'synthetic-target')
        self.assertEqual(replace.call_count, 5)

    def test_other_filesystem_errors_are_not_retried(self):
        with patch.object(state.os, 'replace', side_effect=FileNotFoundError('synthetic missing path')) as replace, patch.object(state.time, 'sleep') as sleep:
            with self.assertRaises(FileNotFoundError):
                state._atomic_replace('synthetic-temp', 'synthetic-target')
        replace.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
