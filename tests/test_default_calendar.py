import json
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from outputs.formfiller import default_calendar, runner
from outputs.formfiller.calendar import (CalendarError, default_calendar_summary, load_calendar_or_default,
                                         load_default_calendar)

SOURCE = Path(default_calendar.__file__)


class DefaultCalendarDataTests(unittest.TestCase):
    def test_data_is_well_formed_and_date_only(self):
        days = default_calendar.SCHOOL_DAYS
        self.assertEqual(len(days), 171)
        self.assertEqual(list(days), sorted(set(days)))
        self.assertTrue(set(default_calendar.EARLY_RELEASE_DAYS) <= set(days))
        self.assertEqual(len(default_calendar.EARLY_RELEASE_DAYS), 2)
        start, end = default_calendar.COVERAGE_START, default_calendar.COVERAGE_END
        self.assertTrue(all(start <= day <= end for day in days))
        for day in days:
            self.assertLess(date.fromisoformat(day).weekday(), 5, day)

    def test_no_district_name_or_provenance_in_the_shipped_module(self):
        text = SOURCE.read_text(encoding="utf-8")
        names = "|".join(("pear" + "land", "p" + "isd"))
        self.assertIsNone(re.search(rf"(?i){names}|@|https?://|[A-Z]:\\", text))

    def test_school_non_school_and_out_of_range_dates(self):
        first = default_calendar.SCHOOL_DAYS[0]
        self.assertTrue(load_default_calendar(first))
        saturday = date.fromisoformat(first) + timedelta(days=(5 - date.fromisoformat(first).weekday()) % 7 or 7)
        self.assertFalse(load_default_calendar(saturday))
        for outside in ("2026-08-18", "2027-05-28", "2025-01-01"):
            with self.assertRaises(CalendarError) as caught:
                load_default_calendar(outside)
            self.assertEqual(caught.exception.code, "outside_coverage")

    def test_summary_has_only_coverage_and_count(self):
        self.assertEqual(set(default_calendar_summary()), {"coverage_start", "coverage_end", "school_day_count"})
        self.assertEqual(default_calendar_summary()["school_day_count"], 171)


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "calendar.json"
        self.school_day = default_calendar.SCHOOL_DAYS[3]

    def private(self, **updates):
        document = {"schema_version": 1, "source": "SchoolDays", "approved": True,
                    "coverage_start": "2026-10-01", "coverage_end": "2026-10-03", "complete": True,
                    "exported_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "school_days": ["2026-10-01"], "non_school_days": []}
        document.update(updates)
        self.path.write_text(json.dumps(document), encoding="utf-8")

    def test_missing_private_calendar_uses_the_built_in_one(self):
        self.assertTrue(load_calendar_or_default(self.path, self.school_day))

    def test_valid_private_calendar_wins_over_the_built_in_one(self):
        self.private()
        self.assertFalse(load_calendar_or_default(self.path, "2026-10-02"))
        with self.assertRaises(CalendarError) as caught:
            load_calendar_or_default(self.path, self.school_day)
        self.assertEqual(caught.exception.code, "outside_coverage")

    def test_present_but_bad_private_calendar_never_falls_back(self):
        for updates, code in (({"approved": False}, "unapproved"),
                              ({"exported_at_utc": "2020-01-01T00:00:00Z"}, "stale_export")):
            self.private(**updates)
            with self.assertRaises(CalendarError) as caught:
                load_calendar_or_default(self.path, "2026-10-01")
            self.assertEqual(caught.exception.code, code)
        self.path.write_text("not json", encoding="utf-8")
        with self.assertRaises(CalendarError) as caught:
            load_calendar_or_default(self.path, self.school_day)
        self.assertEqual(caught.exception.code, "invalid_json")

    def test_runner_gate_falls_back_only_when_calendar_is_absent(self):
        config = Path(self.tempdir.name)
        today = date.fromisoformat(self.school_day)
        self.assertTrue(runner._load_calendar({}, config, today))
        self.path.write_text("{}", encoding="utf-8")
        with self.assertRaises(CalendarError):
            runner._load_calendar({}, config, today)


if __name__ == "__main__":
    unittest.main()
