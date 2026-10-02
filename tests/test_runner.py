import builtins
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from outputs.formfiller import runner
from outputs.formfiller.state import StateStore
from outputs.formfiller.ownership import bind_runtime


class FakeBrowser:
    instances = []
    mismatch_alias = None
    fail_after_click_alias = None
    fail_before_click_alias = None

    def __init__(self, config):
        self.config = config
        self.previewed = []
        self.submitted = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def inspect(self, form):
        if form["alias"] == self.mismatch_alias:
            return {"questions": [{"label": "changed"}]}
        return form["schema"]

    def preview(self, form, today):
        self.previewed.append(form["alias"])

    def submit(self, form, today, before_submit_callback):
        if form["alias"] == self.fail_before_click_alias:
            raise runner.BrowserError("CONTROL_CHANGED")
        before_submit_callback()
        self.submitted.append(form["alias"])
        if form["alias"] == self.fail_after_click_alias:
            raise runner.BrowserError("NETWORK_DROPPED")

    def login(self, form):
        return None


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "config"
        self.config.mkdir()
        self.state_dir = self.root / "state"
        bind_runtime(self.config.parent, self.state_dir.parent)
        self.today = date(2026, 10, 1)
        self.forms = [
            {"alias": f"F{i:02d}", "url": f"https://example.invalid/form/{i}",
             "schema": {"questions": [{"label": f"Q{i}", "kind": "text"}]},
             "answers": [{"value": "fixed"}]}
            for i in range(1, 11)
        ]
        (self.config / "forms.json").write_text(json.dumps({"forms": self.forms}), encoding="utf-8")
        (self.config / "settings.json").write_text(json.dumps({
            "live_enabled": True, "calendar_path": "calendar.json", "browser_profile_path": "profile"
        }), encoding="utf-8")
        (self.config / "calendar.json").write_text("{}", encoding="utf-8")
        FakeBrowser.instances = []
        FakeBrowser.mismatch_alias = None
        FakeBrowser.fail_after_click_alias = None
        FakeBrowser.fail_before_click_alias = None
        self.patchers = [
            patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local"), "FORM_FILLER_WORKSPACE": "", "FORM_FILLER_RUNTIME": "", "FORM_FILLER_INSTALLED_APP": ""}),
            patch.object(runner, "_today", return_value=self.today),
            patch.object(runner, "load_calendar", return_value=True),
            patch.object(runner, "BrowserSession", FakeBrowser),
            patch.object(builtins, "input", return_value=""),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.temp.cleanup()

    def _args(self, *extra):
        return ["--config-dir", str(self.config), "--state-dir", str(self.state_dir), *extra]

    def _run(self, *extra):
        return runner.run(self._args(*extra), project_root=self.root)

    def _approve_all(self):
        store = StateStore(self.state_dir, self.today)
        for form in self.forms:
            schema_fp = runner._schema_fingerprint(form["schema"])
            config_fp = runner._config_fingerprint(form)
            store.record_schema(form["alias"], schema_fp)
            store.record_schema(form["alias"], schema_fp, approved=True, config_fingerprint=config_fp)

    def test_calendar_age_failure_stops_before_browser(self):
        class CalendarError(Exception):
            code = "calendar_stale"

        runner.CalendarError = CalendarError
        runner.load_calendar = lambda *_args, **_kwargs: (_ for _ in ()).throw(CalendarError())
        result = self._run()
        self.assertEqual(result, runner.EXIT_CONFIG)
        self.assertEqual(FakeBrowser.instances, [])
        event = (self.state_dir / self.today.isoformat() / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"status":"calendar_error"', event)

    def test_unpaired_runtime_owner_blocks_live_before_browser(self):
        (self.root / ".formfiller-owner.json").unlink()
        result = runner.run(self._args("--live"), project_root=self.root / "alternate-root")
        self.assertEqual(result, runner.EXIT_CONFIG)
        self.assertEqual(FakeBrowser.instances, [])

    def test_migration_gate_at_runner_start_blocks_before_state_lock(self):
        gate = self.root / ".migration.lock"
        gate.write_text("fixture", encoding="utf-8")
        result = self._run("--live")
        self.assertEqual(result, runner.EXIT_CONFIG)
        self.assertEqual(FakeBrowser.instances, [])
        self.assertFalse((self.state_dir / ".runner.lock").exists())

    def test_migration_gate_race_before_browser_start_fails_closed(self):
        with patch.object(runner, "_migration_in_progress", side_effect=[False, False, True]):
            result = self._run("--live")
        self.assertEqual(result, runner.EXIT_CONFIG)
        self.assertEqual(FakeBrowser.instances, [])

    def test_inspection_saves_observed_schema_for_review(self):
        result = self._run("--inspect", "F01")
        self.assertEqual(result, runner.EXIT_OK)
        saved = self.config / "observed" / "F01.schema.json"
        self.assertTrue(saved.exists())
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), self.forms[0]["schema"])

    def test_live_switch_requires_literal_boolean(self):
        (self.config / "settings.json").write_text(json.dumps({"live_enabled": "false"}), encoding="utf-8")
        result = self._run("--live")
        self.assertEqual(result, runner.EXIT_CONFIG)
        self.assertEqual(FakeBrowser.instances, [])

    def test_non_school_day_is_persisted_without_opening_browser(self):
        runner.load_calendar = lambda *_args, **_kwargs: False
        result = self._run()
        self.assertEqual(result, runner.EXIT_NOT_SCHOOL_DAY)
        event = (self.state_dir / self.today.isoformat() / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"status":"calendar_blocked"', event)
        self.assertEqual(FakeBrowser.instances, [])

    def test_preflight_mismatch_blocks_every_submit(self):
        self._approve_all()
        FakeBrowser.mismatch_alias = "F05"
        result = self._run("--live")
        self.assertEqual(result, runner.EXIT_CONFIG)
        self.assertEqual(FakeBrowser.instances[0].submitted, [])
        self.assertEqual(StateStore(self.state_dir, self.today).read("F05")["status"], "failed")

    def test_before_click_failure_is_the_only_state_resume_can_retry(self):
        self._approve_all()
        FakeBrowser.fail_before_click_alias = "F01"
        first = self._run("--live")
        self.assertEqual(first, runner.EXIT_BROWSER)
        store = StateStore(self.state_dir, self.today)
        self.assertEqual(store.read("F01")["status"], "failed")
        self.assertEqual(FakeBrowser.instances[-1].submitted, [])

        FakeBrowser.fail_before_click_alias = None
        second = self._run("--live", "--resume")
        self.assertEqual(second, runner.EXIT_BROWSER)
        self.assertEqual(FakeBrowser.instances[-1].submitted, ["F01"])
        self.assertEqual(store.read("F01")["status"], "submitted")

    def test_date_rollover_before_click_marks_failure_without_submission(self):
        self._approve_all()
        with patch.object(runner, "_today", side_effect=[self.today, date(2026, 10, 2)]):
            result = self._run("--live")
        self.assertEqual(result, runner.EXIT_BROWSER)
        self.assertEqual(FakeBrowser.instances[-1].submitted, [])
        self.assertEqual(StateStore(self.state_dir, self.today).read("F01")["status"], "failed")

    def test_calendar_gate_is_rechecked_before_click(self):
        self._approve_all()
        with patch.object(runner, "load_calendar", side_effect=[True, False]):
            result = self._run("--live")
        self.assertEqual(result, runner.EXIT_BROWSER)
        self.assertEqual(FakeBrowser.instances[-1].submitted, [])
        self.assertEqual(StateStore(self.state_dir, self.today).read("F01")["status"], "failed")

    def test_uncertain_result_never_retries_and_resume_skips_it(self):
        self._approve_all()
        FakeBrowser.fail_after_click_alias = "F01"
        first = self._run("--live")
        self.assertEqual(first, runner.EXIT_BROWSER)
        store = StateStore(self.state_dir, self.today)
        self.assertEqual(store.read("F01")["status"], "uncertain")
        FakeBrowser.fail_after_click_alias = None
        second = self._run("--live", "--resume")
        self.assertEqual(second, runner.EXIT_BROWSER)
        self.assertEqual(FakeBrowser.instances[-1].submitted, [])

    def test_submitted_alias_cannot_be_duplicated_by_config_edit(self):
        self._approve_all()
        self.assertEqual(self._run("--live"), runner.EXIT_OK)
        self.forms[0]["answers"] = [{"value": "changed"}]
        (self.config / "forms.json").write_text(json.dumps({"forms": self.forms}), encoding="utf-8")
        result = self._run("--live")
        self.assertEqual(result, runner.EXIT_OK)
        self.assertEqual(FakeBrowser.instances[-1].submitted, [])


if __name__ == "__main__":
    unittest.main()
