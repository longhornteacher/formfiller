import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from outputs.formfiller import runner, scheduling, taskplan
from outputs.formfiller.state import StateError, StateStore

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class FakeScheduler:
    def __init__(self, existing=()):
        self.tasks = {name: "old" for name in existing}
        self.deleted = []

    def run_tasks(self):
        return [name for name in self.tasks if name.startswith(taskplan.RUN_PREFIX)]

    def clear_run_tasks(self):
        for name in self.run_tasks():
            self.deleted.append(name)
            del self.tasks[name]

    def create(self, name, xml):
        self.tasks[name] = xml

    def delete(self, name):
        self.deleted.append(name)
        self.tasks.pop(name, None)


class TaskXmlTests(unittest.TestCase):
    def test_run_task_is_hidden_windowless_and_bounded(self):
        day = date(2026, 10, 21)
        when = datetime(2026, 10, 21, 13, 7)
        end = datetime(2026, 10, 21, 15, 30)
        root = ET.fromstring(taskplan.run_task_xml(when, end, "C:/app/.venv/Scripts/python.exe", "C:/app"))
        self.assertEqual(root.find("t:Triggers/t:TimeTrigger/t:StartBoundary", NS).text, "2026-10-21T13:07:00")
        self.assertEqual(root.find("t:Triggers/t:TimeTrigger/t:EndBoundary", NS).text, "2026-10-21T15:30:00")
        settings = root.find("t:Settings", NS)
        for tag, expected in (("Hidden", "true"), ("StartWhenAvailable", "true"), ("WakeToRun", "false"),
                              ("DeleteExpiredTaskAfter", "PT0S"), ("ExecutionTimeLimit", "PT30M")):
            self.assertEqual(settings.find(f"t:{tag}", NS).text, expected, tag)
        arguments = root.find("t:Actions/t:Exec/t:Arguments", NS).text
        self.assertEqual(arguments, "-B -m formfiller.taskplan run")
        self.assertNotIn("powershell", taskplan.run_task_xml(when, end, "python.exe", "C:/app").lower())
        self.assertTrue(day)

    def test_planner_has_daily_and_logon_triggers_and_no_repetition(self):
        xml = taskplan.planner_task_xml(date(2026, 10, 21), "python.exe", "C:/app")
        root = ET.fromstring(xml)
        self.assertIsNotNone(root.find("t:Triggers/t:CalendarTrigger/t:ScheduleByDay", NS))
        self.assertIsNotNone(root.find("t:Triggers/t:LogonTrigger", NS))
        self.assertNotIn("Repetition", xml)
        self.assertEqual(root.find("t:Actions/t:Exec/t:Arguments", NS).text, "-B -m formfiller.taskplan plan")


class ReplaceRunTasksTests(unittest.TestCase):
    day = date(2026, 10, 21)

    def instant(self, hour, minute=0):
        return datetime(2026, 10, 21, hour, minute, tzinfo=scheduling.ZONE)

    def test_clears_yesterday_and_registers_one_task_per_future_slot(self):
        scheduler = FakeScheduler(["\\FormFiller\\Run 1305", "\\FormFiller\\Daily Plan"])
        count = taskplan.replace_run_tasks(scheduler, self.day, [750, 800, 900], self.instant(6), "python.exe", "C:/app")
        self.assertEqual(count, 3)
        self.assertIn("\\FormFiller\\Run 1305", scheduler.deleted)
        self.assertIn("\\FormFiller\\Daily Plan", scheduler.tasks)  # planner untouched
        self.assertEqual(len(scheduler.run_tasks()), 3)

    def test_overdue_slots_collapse_into_one_catch_up_and_nothing_after_window(self):
        scheduler = FakeScheduler()
        count = taskplan.replace_run_tasks(scheduler, self.day, [750, 760, 770, 900], self.instant(14), "python.exe", "C:/app")
        self.assertEqual(count, 2)  # one catch-up for 12:30-12:50 plus the 15:00 slot
        self.assertEqual(len(scheduler.run_tasks()), 2)
        closed = FakeScheduler()
        self.assertEqual(taskplan.replace_run_tasks(closed, self.day, [750], self.instant(15, 30), "python.exe", "C:/app"), 0)

    def test_no_aliases_in_task_names_or_xml(self):
        scheduler = FakeScheduler()
        taskplan.replace_run_tasks(scheduler, self.day, [750], self.instant(6), "python.exe", "C:/app")
        for name, xml in scheduler.tasks.items():
            self.assertRegex(name, r"^\\FormFiller\\Run \d{4}$")
            self.assertNotIn("F01", xml)


class SchedulerWrapperTests(unittest.TestCase):
    def test_queries_creates_and_deletes_with_schtasks_only(self):
        calls = []

        def run(arguments, **options):
            calls.append(arguments)
            output = '"\\FormFiller\\Run 1307","N/A","Ready"\n"\\Other","N/A","Ready"\n"\\FormFiller\\Daily Plan","N/A","Ready"\n'
            return SimpleNamespace(returncode=0, stdout=output, stderr="")

        scheduler = taskplan.Scheduler(run)
        self.assertEqual(scheduler.run_tasks(), ["\\FormFiller\\Run 1307"])
        scheduler.create("\\FormFiller\\Run 1400", "<Task/>")
        scheduler.delete("\\FormFiller\\Run 1307")
        self.assertEqual([c[1] for c in calls], ["/Query", "/Create", "/Delete"])
        self.assertTrue(all(c[0] == "schtasks.exe" for c in calls))
        self.assertIn("/XML", calls[1])

    def test_register_failure_is_a_fixed_code(self):
        scheduler = taskplan.Scheduler(lambda a, **o: SimpleNamespace(returncode=1, stdout="", stderr="C:\\private"))
        with self.assertRaises(taskplan.PlanError) as caught:
            scheduler.create("\\FormFiller\\Run 1400", "<Task/>")
        self.assertEqual(caught.exception.code, "task_register_failed")


class SyncTodayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config, self.state_dir = root / "ws" / "config", root / "rt" / "state"
        self.config.mkdir(parents=True)
        self.today = date(2026, 10, 21)
        forms = [{"id": f"F{i:02}", "alias": f"F{i:02}", "name": f"Form {i}", "url": "https://forms.example/x",
                  "schema": {"questions": [{"id": "q", "type": "text", "title": "Q"}]},
                  "answers": [{"value": "fixed"}], "scheduled": True} for i in range(1, 11)]
        (self.config / "forms.json").write_text(json.dumps({"forms": forms}))
        self.settings(live=True)
        self.instant = datetime(2026, 10, 21, 6, 0, tzinfo=scheduling.ZONE)
        patchers = [patch("outputs.formfiller.ownership.verify_runtime_owner"),
                    patch.object(runner, "_load_calendar", return_value=True)]
        self.calendar = patchers[1]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def settings(self, live):
        (self.config / "settings.json").write_text(json.dumps({"live_enabled": live}))

    def sync(self, scheduler, instant=None):
        return taskplan.sync_today(self.config, self.state_dir, scheduler=scheduler, python="python.exe",
                                   snapshot="C:/app", instant=instant or self.instant)

    def test_morning_plan_creates_one_task_per_form_and_is_idempotent(self):
        scheduler = FakeScheduler()
        result = self.sync(scheduler)
        self.assertEqual(result, {"code": "planned", "tasks": 10})
        names = sorted(scheduler.run_tasks())
        self.assertEqual(self.sync(scheduler)["tasks"], 10)
        self.assertEqual(sorted(scheduler.run_tasks()), names)
        slots = json.loads((self.state_dir / "2026-10-21" / "schedule.json").read_text())["slots"]
        self.assertEqual(len(set(slots.values())), 10)

    def test_yesterdays_timing_is_deleted(self):
        yesterday = StateStore(self.state_dir, date(2026, 10, 20))
        scheduling.plan(yesterday, [{"alias": "F01"}], datetime(2026, 10, 20, 9, tzinfo=scheduling.ZONE))
        self.assertTrue((yesterday.day_dir / "schedule.json").exists())
        self.sync(FakeScheduler(["\\FormFiller\\Run 1305"]))
        self.assertFalse((yesterday.day_dir / "schedule.json").exists())

    def test_non_school_day_clears_tasks_and_plans_nothing(self):
        self.calendar.stop()
        with patch.object(runner, "_load_calendar", return_value=False):
            scheduler = FakeScheduler(["\\FormFiller\\Run 1305"])
            self.assertEqual(self.sync(scheduler), {"code": "not_school_day", "tasks": 0})
            self.assertEqual(scheduler.run_tasks(), [])
        self.assertFalse((self.state_dir / "2026-10-21" / "schedule.json").exists())

    def test_live_disabled_and_closed_window_register_nothing(self):
        self.settings(live=False)
        scheduler = FakeScheduler()
        self.assertEqual(self.sync(scheduler)["code"], "live_disabled")
        self.settings(live=True)
        late = datetime(2026, 10, 21, 16, 0, tzinfo=scheduling.ZONE)
        self.assertEqual(self.sync(scheduler, late)["tasks"], 0)
        self.assertEqual(scheduler.run_tasks(), [])

    def test_claimed_forms_do_not_get_new_tasks(self):
        scheduler = FakeScheduler()
        self.sync(scheduler)
        store = StateStore(self.state_dir, self.today)
        data = scheduling.plan(store, [{"alias": f"F{i:02}"} for i in range(1, 11)], self.instant)
        with store.lock():
            scheduling.claim(store, [{"alias": f"F{i:02}"} for i in range(1, 11)], self.instant)
        self.assertEqual(self.sync(scheduler)["code"], "nothing_due")
        self.assertEqual(scheduler.run_tasks(), [])
        self.assertTrue(data)

    def test_busy_lock_is_reported_so_callers_can_retry(self):
        store = StateStore(self.state_dir, self.today)
        with store.lock():
            with self.assertRaises(StateError) as caught:
                self.sync(FakeScheduler())
        self.assertEqual(caught.exception.code, "lock_exists")


class RetryAndUiTests(unittest.TestCase):
    def test_lock_retry_waits_only_for_lock_exists(self):
        results = [(5, "error code=lock_exists"), (5, "error code=lock_exists"), (0, "run_exit=0")]
        sleeps, ticks = [], iter(range(0, 10000, 1))
        code, text = taskplan.run_with_lock_retry(lambda: results.pop(0), sleep=sleeps.append,
                                                  clock=lambda: next(ticks), wait=600, poll=15)
        self.assertEqual((code, len(sleeps)), (0, 2))
        code, _ = taskplan.run_with_lock_retry(lambda: (4, "failed alias=F01 code=browser_error"), sleep=sleeps.append)
        self.assertEqual((code, len(sleeps)), (4, 2))

    def test_lock_retry_gives_up_at_deadline(self):
        ticks = iter([0, 100, 500, 800])
        code, _ = taskplan.run_with_lock_retry(lambda: (5, "code=lock_exists"), sleep=lambda s: None,
                                               clock=lambda: next(ticks), wait=600, poll=15)
        self.assertEqual(code, 5)

    def test_ui_sync_refuses_development_checkout(self):
        with patch.object(taskplan, "resolve_workspace", return_value=SimpleNamespace(installed_app=None)):
            result = taskplan.sync_for_ui(Path("c"), Path("s"), scheduler=FakeScheduler())
        self.assertEqual(result["code"], "not_installed_snapshot")

    def test_ui_sync_retries_busy_lock_then_succeeds(self):
        calls = []

        def fake(*args, **kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise StateError("lock_exists")
            return {"code": "planned", "tasks": 2}

        designated = SimpleNamespace(installed_app=taskplan.ROOT)
        with patch.object(taskplan, "resolve_workspace", return_value=designated), \
                patch.object(taskplan, "sync_today", fake):
            result = taskplan.sync_for_ui(Path("c"), Path("s"), sleep=lambda s: None)
        self.assertEqual((result["code"], len(calls)), ("planned", 3))


if __name__ == "__main__":
    unittest.main()
