import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from outputs.formfiller import scheduling
from outputs.formfiller.state import StateStore, StateError


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.instant = datetime(2026, 10, 21, 9, tzinfo=scheduling.ZONE)
        self.store = StateStore(Path(self.temp.name), self.instant.date())
        self.forms = [{"alias": f"F{i:02}"} for i in range(10)]

    def test_spread_stable_unique_and_local_only(self):
        data = scheduling.plan(self.store, self.forms, self.instant)
        slots = list(data["slots"].values())
        self.assertEqual(len(set(slots)), 10)
        self.assertTrue(all(720 <= value < 930 for value in slots))
        self.assertLess(min(slots), 741)
        self.assertGreaterEqual(max(slots), 909)
        self.assertEqual(scheduling.plan(self.store, list(reversed(self.forms)), self.instant), data)
        self.assertEqual(set(data), {"date", "slots", "claimed"})

    def test_late_add_does_not_move_existing_slots(self):
        before = scheduling.plan(self.store, self.forms, self.instant)["slots"]
        after = scheduling.plan(self.store, self.forms + [{"alias": "added"}], self.instant.replace(hour=14))["slots"]
        self.assertEqual({key: after[key] for key in before}, before)
        self.assertGreater(after["added"], 840)

    def test_pause_archive_and_claim_prevent_dispatch(self):
        scheduling.plan(self.store, self.forms, self.instant)
        afternoon = self.instant.replace(hour=15, minute=29)
        due = scheduling.due(self.store, self.forms, afternoon)
        self.assertEqual(len(due), 10)
        scheduling.claim(self.store, due, afternoon)
        self.assertEqual(scheduling.due(self.store, self.forms, afternoon), [])
        fresh_store = StateStore(Path(self.temp.name), self.instant.date())
        self.assertEqual(scheduling.due(fresh_store, self.forms, afternoon), [])

    def test_failed_uncertain_submitted_are_never_retried(self):
        scheduling.plan(self.store, self.forms, self.instant)
        for form, status in zip(self.forms, ("failed", "uncertain", "submitted")):
            alias = form["alias"]
            self.store.bind_config(alias, "a" * 64)
            self.store.transition(alias, "pending", "failed" if status == "failed" else "submitting")
            if status != "failed":
                self.store.transition(alias, "submitting", status)
        due = scheduling.due(self.store, self.forms, self.instant.replace(hour=15, minute=29))
        self.assertEqual(len(due), 7)

    def test_window_and_new_day(self):
        scheduling.plan(self.store, self.forms, self.instant)
        self.assertEqual(scheduling.due(self.store, self.forms, self.instant), [])
        self.assertEqual(scheduling.due(self.store, self.forms, self.instant.replace(hour=15, minute=30)), [])
        tomorrow = self.instant + timedelta(days=1)
        new = StateStore(self.store.root, tomorrow.date())
        self.assertEqual(len(scheduling.plan(new, self.forms, tomorrow)["slots"]), 10)

    def test_paused_or_removed_templates_not_due(self):
        scheduling.plan(self.store, self.forms, self.instant)
        self.forms[0]["scheduled"] = False
        due = scheduling.due(self.store, self.forms[:-1], self.instant.replace(hour=15, minute=29))
        self.assertEqual(len(due), 8)

    def test_corrupt_plan_fails_closed(self):
        scheduling.plan(self.store, self.forms, self.instant)
        path = self.store.day_dir / "schedule.json"
        path.write_text(json.dumps({"date": self.store.day, "slots": {"F00": 9999}, "claimed": []}))
        with self.assertRaises(StateError):
            scheduling.due(self.store, self.forms, self.instant)
