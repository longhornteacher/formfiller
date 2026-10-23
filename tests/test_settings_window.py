import http.client
import json
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from outputs.formfiller import runner, scheduling, taskplan, web
from outputs.formfiller.state import StateStore
from tests.test_taskplan import FakeScheduler, NS


class WindowValidationTests(unittest.TestCase):
    def tearDown(self):
        scheduling.apply({})

    def test_missing_keys_use_the_existing_defaults(self):
        self.assertEqual(scheduling.parse_window({"live_enabled": False})[:3], (720, 930, "America/Chicago"))
        scheduling.apply({})
        self.assertEqual((scheduling.START, scheduling.END, scheduling.ZONE_NAME), (720, 930, "America/Chicago"))

    def test_valid_custom_window_and_zone(self):
        scheduling.apply({"submit_window_start": "08:15", "submit_window_end": "10:00", "time_zone": "America/Denver"})
        self.assertEqual((scheduling.START, scheduling.END), (495, 600))
        self.assertEqual(scheduling.window_label(), "08:15–10:00 America/Denver")
        self.assertEqual(scheduling.now().tzinfo.key, "America/Denver")

    def test_rejects_bad_values_with_fixed_codes(self):
        for bad in ({"submit_window_start": "15:30", "submit_window_end": "12:00"},
                    {"submit_window_start": "12:00", "submit_window_end": "12:00"},
                    {"submit_window_start": "25:00"}, {"submit_window_start": "9:00"},
                    {"submit_window_end": 1530}, {"submit_window_start": "ab:cd"}):
            with self.assertRaises(ValueError) as caught:
                scheduling.parse_window(bad)
            self.assertEqual(str(caught.exception), "settings_window_invalid", bad)
        for bad in ({"time_zone": "Mars/Base"}, {"time_zone": ""}, {"time_zone": 5}, {"time_zone": "../etc"},
                    {"time_zone": "/etc/passwd"}):
            with self.assertRaises(ValueError) as caught:
                scheduling.parse_window(bad)
            self.assertEqual(str(caught.exception), "settings_time_zone_invalid", bad)
        # Invalid input never changes the active window.
        self.assertEqual((scheduling.START, scheduling.END), (720, 930))


class WindowPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(scheduling.apply, {})
        scheduling.apply({"submit_window_start": "09:00", "submit_window_end": "10:00", "time_zone": "America/Los_Angeles"})
        self.instant = datetime(2026, 10, 21, 7, tzinfo=scheduling.ZONE)
        self.store = StateStore(Path(self.temp.name), self.instant.date())
        self.forms = [{"alias": f"F{i:02}"} for i in range(6)]

    def test_slots_stay_inside_the_custom_window(self):
        slots = scheduling.plan(self.store, self.forms, self.instant)["slots"]
        self.assertEqual(len(slots), 6)
        self.assertTrue(all(540 <= value < 600 for value in slots.values()))

    def test_due_only_inside_the_custom_window(self):
        scheduling.plan(self.store, self.forms, self.instant)
        self.assertEqual(scheduling.due(self.store, self.forms, self.instant.replace(hour=12)), [])
        self.assertEqual(len(scheduling.due(self.store, self.forms, self.instant.replace(hour=9, minute=59))), 6)

    def test_window_change_replans_unclaimed_and_keeps_claimed(self):
        slots = scheduling.plan(self.store, self.forms, self.instant)["slots"]
        with self.store.lock():
            scheduling.claim(self.store, [self.forms[0]], self.instant)
        scheduling.apply({"submit_window_start": "13:00", "submit_window_end": "14:00", "time_zone": "America/Los_Angeles"})
        data = scheduling.plan(self.store, self.forms, self.instant)
        self.assertEqual(data["slots"]["F00"], slots["F00"])
        self.assertTrue(all(780 <= data["slots"][f["alias"]] < 840 for f in self.forms[1:]))

    def test_central_to_local_follows_the_configured_zone(self):
        local = taskplan.central_to_local(date(2026, 10, 21), 540)
        expected = datetime(2026, 10, 21, 9, tzinfo=scheduling.ZONE).astimezone().replace(tzinfo=None)
        self.assertEqual(local, expected)

    def test_planner_runs_before_an_early_window(self):
        self.assertEqual(taskplan.planner_minute(), 360)
        scheduling.apply({"submit_window_start": "06:00", "submit_window_end": "07:00"})
        self.assertEqual(taskplan.planner_minute(), 330)
        scheduling.apply({})
        self.assertEqual(taskplan.planner_minute(), 360)


class SyncWithSettingsTests(unittest.TestCase):
    day = date(2026, 10, 21)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(scheduling.apply, {})
        root = Path(self.temp.name)
        self.config, self.state_dir = root / "ws" / "config", root / "rt" / "state"
        self.config.mkdir(parents=True)
        forms = [{"id": f"F{i:02}", "alias": f"F{i:02}", "name": f"Form {i}", "url": "https://forms.example/x",
                  "schema": {"questions": [{"id": "q", "type": "text", "title": "Q"}]},
                  "answers": [{"value": "fixed"}], "scheduled": True} for i in range(1, 4)]
        (self.config / "forms.json").write_text(json.dumps({"forms": forms}))
        for target in (patch("outputs.formfiller.ownership.verify_runtime_owner"),
                       patch.object(runner, "_load_calendar", return_value=True)):
            target.start()
            self.addCleanup(target.stop)

    def settings(self, **extra):
        (self.config / "settings.json").write_text(json.dumps({"live_enabled": True, **extra}))

    def sync(self, scheduler, instant):
        return taskplan.sync_today(self.config, self.state_dir, scheduler=scheduler, python="python.exe",
                                   snapshot="C:/app", instant=instant)

    def test_defaults_without_keys_behave_as_before(self):
        self.settings()
        scheduler = FakeScheduler()
        self.assertEqual(self.sync(scheduler, datetime(2026, 10, 21, 6, tzinfo=scheduling.ZONE))["code"], "planned")
        slots = json.loads((self.state_dir / "2026-10-21" / "schedule.json").read_text())["slots"]
        self.assertTrue(all(720 <= v < 930 for v in slots.values()))

    def test_custom_window_controls_slots_end_boundary_and_closing(self):
        self.settings(submit_window_start="09:00", submit_window_end="10:00", time_zone="America/Denver")
        scheduler = FakeScheduler()
        morning = datetime(2026, 10, 21, 6, tzinfo=scheduling.ZONE)
        result = self.sync(scheduler, morning)
        self.assertEqual(result["code"], "planned")
        slots = json.loads((self.state_dir / "2026-10-21" / "schedule.json").read_text())["slots"]
        self.assertTrue(all(540 <= v < 600 for v in slots.values()))
        end = datetime(2026, 10, 21, 10, tzinfo=scheduling.ZONE).astimezone().replace(tzinfo=None)
        for xml in scheduler.tasks.values():
            root = ET.fromstring(xml)
            self.assertEqual(root.find("t:Triggers/t:TimeTrigger/t:EndBoundary", NS).text, end.strftime("%Y-%m-%dT%H:%M:%S"))
        # 10:30 Denver is after the custom window even though it is inside the old default window.
        closed = datetime(2026, 10, 21, 10, 30, tzinfo=scheduling.ZONE)
        self.assertEqual(self.sync(scheduler, closed), {"code": "window_closed", "tasks": 0})
        self.assertEqual(scheduler.run_tasks(), [])

    def test_invalid_settings_register_nothing(self):
        self.settings(submit_window_start="16:00", submit_window_end="12:00")
        scheduler = FakeScheduler(["\\FormFiller\\Run 1305"])
        result = self.sync(scheduler, datetime(2026, 10, 21, 6, tzinfo=scheduling.ZONE))
        self.assertEqual(result, {"code": "settings_window_invalid", "tasks": 0})
        self.assertEqual(scheduler.run_tasks(), [])

    def test_changing_the_window_reconciles_existing_tasks(self):
        self.settings()
        scheduler = FakeScheduler()
        morning = datetime(2026, 10, 21, 6, tzinfo=scheduling.ZONE)
        self.sync(scheduler, morning)
        before = set(scheduler.run_tasks())
        self.settings(submit_window_start="08:00", submit_window_end="09:00")
        self.sync(scheduler, morning)
        after = scheduler.run_tasks()
        self.assertTrue(after)
        self.assertTrue(all("0800" <= name[-4:] < "0900" for name in after), after)
        self.assertFalse(before & set(after))

    def test_ui_refresh_reregisters_planner_only_when_asked(self):
        self.settings()
        scheduler = FakeScheduler()
        workspace = SimpleNamespace(installed_app=taskplan.ROOT)
        with patch.object(taskplan, "resolve_workspace", return_value=workspace), \
                patch.object(taskplan, "install_planner") as planner, \
                patch.object(taskplan, "sync_today", return_value={"code": "planned", "tasks": 0}):
            taskplan.sync_for_ui(self.config, self.state_dir, scheduler=scheduler)
            planner.assert_not_called()
            taskplan.sync_for_ui(self.config, self.state_dir, scheduler=scheduler, refresh_planner=True)
            planner.assert_called_once()


class SettingsEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(scheduling.apply, {})
        web.initialize_demo(self.root / "config", self.root / "state")
        self.app = web.WebApp(self.root / "config", self.root / "state", self.root / "profile")
        self.server = web.Server(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        headers = {"Content-Type": "application/json", "X-FormFiller-Token": self.app.token}
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = connection.getresponse()
        value = json.loads(response.read())
        connection.close()
        return response.status, value

    def stored(self):
        return json.loads((self.root / "config" / "settings.json").read_text())

    def test_defaults_are_reported(self):
        status, data = self.request("GET", "/api/settings/window")
        self.assertEqual(status, 200)
        self.assertEqual((data["submit_window_start"], data["submit_window_end"], data["time_zone"]),
                         ("12:00", "15:30", "America/Chicago"))

    def test_save_persists_only_window_keys_and_refreshes_tasks(self):
        before = self.stored()
        with patch.object(self.app, "sync_tasks", return_value={"code": "planned", "tasks": 2}) as sync:
            status, data = self.request("PUT", "/api/settings/window", {
                "submit_window_start": "11:00", "submit_window_end": "14:00", "time_zone": "America/New_York"})
        self.assertEqual(status, 200)
        sync.assert_called_once_with(refresh_planner=True)
        after = self.stored()
        self.assertEqual({k: v for k, v in after.items() if k not in ("submit_window_start", "submit_window_end", "time_zone")}, before)
        self.assertIs(after["live_enabled"], False)
        self.assertEqual(after["time_zone"], "America/New_York")
        self.assertTrue(data["saved"])
        self.assertEqual(self.app.status()["schedule_window"], "11:00–14:00 America/New_York")
        with patch.object(self.app, "sync_tasks") as sync:
            self.assertFalse(self.request("PUT", "/api/settings/window", {"time_zone": "America/New_York"})[1]["saved"])
            sync.assert_not_called()

    def test_invalid_values_are_rejected_and_not_saved(self):
        before = self.stored()
        for body, code in (({"submit_window_start": "15:00", "submit_window_end": "12:00"}, "settings_window_invalid"),
                           ({"time_zone": "Nowhere/Land"}, "settings_time_zone_invalid"),
                           ({"live_enabled": True}, "settings_field_unknown")):
            status, data = self.request("PUT", "/api/settings/window", body)
            self.assertEqual(status, 400)
            self.assertEqual(data["error"]["code"], code)
        self.assertEqual(self.stored(), before)


if __name__ == "__main__":
    unittest.main()
