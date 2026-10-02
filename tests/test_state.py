import tempfile
import unittest
from datetime import date
from pathlib import Path

from outputs.formfiller.state import StateError, StateStore


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


if __name__ == "__main__":
    unittest.main()
