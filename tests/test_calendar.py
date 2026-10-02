import csv
import contextlib
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from outputs.formfiller.calendar import CalendarError, import_csv, load_calendar, main


class CalendarGateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.path = self.root / "calendar.json"
        self.now = datetime.now(timezone.utc)
        self.document = {
            "schema_version": 1,
            "source": "SchoolDays",
            "approved": True,
            "coverage_start": "2026-10-01",
            "coverage_end": "2026-10-03",
            "exported_at_utc": self.now.isoformat().replace("+00:00", "Z"),
            "complete": False,
            "school_days": ["2026-10-01"],
            "non_school_days": ["2026-10-02"],
        }
        self.write_document()

    def tearDown(self):
        self.tempdir.cleanup()

    def write_document(self, **updates):
        self.document.update(updates)
        self.path.write_text(json.dumps(self.document), encoding="utf-8")

    def assert_calendar_error(self, code, *args, **kwargs):
        with self.assertRaises(CalendarError) as caught:
            load_calendar(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_returns_true_for_explicit_school_day(self):
        self.assertTrue(load_calendar(self.path, date(2026, 10, 1)))

    def test_returns_false_for_explicit_non_school_day(self):
        self.assertFalse(load_calendar(self.path, "2026-10-02"))

    def test_omitted_date_fails_when_export_is_incomplete(self):
        self.assert_calendar_error("missing_date", self.path, "2026-10-03")

    def test_omitted_date_is_non_school_only_for_complete_export(self):
        self.write_document(complete=True)
        self.assertFalse(load_calendar(self.path, "2026-10-03"))

    def test_unapproved_bootstrap_is_blocked(self):
        self.write_document(approved=False)
        self.assert_calendar_error("unapproved", self.path, "2026-10-01")

    def test_missing_file_fails_closed(self):
        self.assert_calendar_error("missing_calendar", self.root / "absent.json", "2026-10-01")

    def test_invalid_json_fails_closed(self):
        self.path.write_text("{", encoding="utf-8")
        self.assert_calendar_error("invalid_json", self.path, "2026-10-01")

    def test_wrong_source_fails_closed(self):
        self.write_document(source="OtherCalendar")
        self.assert_calendar_error("wrong_source", self.path, "2026-10-01")

    def test_stale_export_fails_closed(self):
        old = self.now - timedelta(days=14, seconds=1)
        self.write_document(exported_at_utc=old.isoformat().replace("+00:00", "Z"))
        self.assert_calendar_error("stale_export", self.path, "2026-10-01")

    def test_future_export_fails_closed(self):
        future = self.now + timedelta(minutes=1)
        self.write_document(exported_at_utc=future.isoformat().replace("+00:00", "Z"))
        self.assert_calendar_error("future_export", self.path, "2026-10-01")

    def test_date_outside_coverage_fails_closed(self):
        self.assert_calendar_error("outside_coverage", self.path, "2026-10-04")

    def test_overlap_between_day_lists_fails_closed(self):
        self.write_document(non_school_days=["2026-10-01"])
        self.assert_calendar_error("invalid_schema", self.path, "2026-10-01")

    def test_invalid_max_age_fails(self):
        with self.assertRaises(CalendarError) as caught:
            load_calendar(self.path, "2026-10-01", max_age_days=-1)
        self.assertEqual(caught.exception.code, "invalid_max_age")


class CalendarImportTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.csv_path = self.root / "SchoolDays.csv"
        self.out_path = self.root / "config" / "calendar.json"
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tempdir.cleanup()

    def write_csv(self, rows, headers=("Date", "IsSchoolDay")):
        with self.csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)

    def run_import(self, *, approved=True, complete=False):
        return import_csv(
            self.csv_path,
            self.out_path,
            "Date",
            "IsSchoolDay",
            "2026-10-01",
            "2026-10-03",
            approved,
            now=self.now,
            complete=complete,
        )

    def test_import_preserves_true_false_rows_and_utc_timestamp(self):
        self.write_csv([
            ("2026-10-01", "TRUE"),
            ("2026-10-02", "no"),
        ])
        result = self.run_import()
        self.assertEqual(result, self.out_path)
        document = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(document["source"], "SchoolDays")
        self.assertEqual(document["school_days"], ["2026-10-01"])
        self.assertEqual(document["non_school_days"], ["2026-10-02"])
        self.assertFalse(document["complete"])
        self.assertEqual(document["exported_at_utc"], self.now.isoformat().replace("+00:00", "Z"))
        self.assertTrue(load_calendar(result, "2026-10-01"))
        self.assertFalse(load_calendar(result, "2026-10-02"))
        with self.assertRaises(CalendarError) as caught:
            load_calendar(result, "2026-10-03")
        self.assertEqual(caught.exception.code, "missing_date")

    def test_incomplete_export_does_not_infer_omissions_as_non_school(self):
        self.write_csv([("2026-10-01", "1")])
        result = self.run_import()
        with self.assertRaises(CalendarError) as caught:
            load_calendar(result, "2026-10-02")
        self.assertEqual(caught.exception.code, "missing_date")

    def test_complete_export_allows_omissions_as_non_school(self):
        self.write_csv([("2026-10-01", "1")])
        result = self.run_import(complete=True)
        self.assertFalse(load_calendar(result, "2026-10-02"))

    def test_unapproved_import_stays_blocked(self):
        self.write_csv([("2026-10-01", "true")])
        result = self.run_import(approved=False)
        with self.assertRaises(CalendarError) as caught:
            load_calendar(result, "2026-10-01")
        self.assertEqual(caught.exception.code, "unapproved")

    def test_duplicate_dates_are_rejected(self):
        self.write_csv([("2026-10-01", "true"), ("2026-10-01", "false")])
        with self.assertRaises(CalendarError) as caught:
            self.run_import()
        self.assertEqual(caught.exception.code, "duplicate_date")

    def test_rows_outside_declared_coverage_are_rejected(self):
        self.write_csv([("2026-09-30", "true")])
        with self.assertRaises(CalendarError) as caught:
            self.run_import()
        self.assertEqual(caught.exception.code, "outside_coverage")

    def test_unrecognized_boolean_is_rejected(self):
        self.write_csv([("2026-10-01", "maybe")])
        with self.assertRaises(CalendarError) as caught:
            self.run_import()
        self.assertEqual(caught.exception.code, "invalid_school_day")

    def test_missing_named_columns_are_rejected(self):
        self.write_csv([("2026-10-01", "true")], headers=("When", "Present"))
        with self.assertRaises(CalendarError) as caught:
            self.run_import()
        self.assertEqual(caught.exception.code, "missing_columns")

    def test_timezone_naive_timestamp_is_rejected(self):
        self.write_csv([("2026-10-01", "true")])
        with self.assertRaises(CalendarError) as caught:
            import_csv(
                self.csv_path, self.out_path, "Date", "IsSchoolDay",
                "2026-10-01", "2026-10-03", True,
                now=datetime(2026, 10, 1),
            )
        self.assertEqual(caught.exception.code, "invalid_timestamp")

    def test_timestamp_is_required_instead_of_stamping_import_time(self):
        self.write_csv([("2026-10-01", "true")])
        with self.assertRaises(CalendarError) as caught:
            import_csv(
                self.csv_path, self.out_path, "Date", "IsSchoolDay",
                "2026-10-01", "2026-10-03", True,
            )
        self.assertEqual(caught.exception.code, "export_timestamp_required")
        self.assertFalse(self.out_path.exists())

    def test_dates_only_import_requires_explicit_mode_and_marks_all_rows_as_school_days(self):
        self.write_csv([("2026-10-01",), ("2026-10-02",)], headers=("Title",))
        result = import_csv(
            self.csv_path, self.out_path, "Title", None,
            "2026-10-01", "2026-10-03", True,
            exported_at=self.now, complete=True, dates_only=True,
        )
        document = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(document["school_days"], ["2026-10-01", "2026-10-02"])
        self.assertEqual(document["non_school_days"], [])
        self.assertTrue(load_calendar(result, "2026-10-01"))

    def test_future_export_timestamp_is_rejected_before_writing(self):
        self.write_csv([("2026-10-01", "true")])
        with self.assertRaises(CalendarError) as caught:
            import_csv(
                self.csv_path, self.out_path, "Date", "IsSchoolDay",
                "2026-10-01", "2026-10-03", True,
                exported_at=self.now + timedelta(minutes=1),
            )
        self.assertEqual(caught.exception.code, "future_export")
        self.assertFalse(self.out_path.exists())


class CalendarCliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.csv_path = self.root / "SchoolDays.csv"
        self.out_path = self.root / "calendar.json"
        self.now = datetime.now(timezone.utc)
        with self.csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Title"])
            writer.writerow(["2026-10-01"])

    def tearDown(self):
        self.tempdir.cleanup()

    def cli_import_args(self, exported_at=None):
        timestamp = exported_at or self.now
        return [
            "import", "--csv", str(self.csv_path),
            "--date-column", "Title", "--dates-only",
            "--coverage-start", "2026-10-01", "--coverage-end", "2026-10-03",
            "--exported-at", timestamp.isoformat().replace("+00:00", "Z"),
            "--approved", "--complete", "--out", str(self.out_path),
        ]

    def test_cli_import_and_check(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(self.cli_import_args())
        self.assertEqual(status, 0)
        self.assertIn("Calendar imported", output.getvalue())

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["check", "--calendar", str(self.out_path), "--date", "2026-10-01"])
        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue().strip(), "School day")

    def test_cli_rejects_future_export_timestamp_without_writing(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            status = main(self.cli_import_args(self.now + timedelta(minutes=1)))
        self.assertEqual(status, 2)
        self.assertIn("future_export", output.getvalue())
        self.assertFalse(self.out_path.exists())

    def test_cli_requires_export_timestamp(self):
        args = self.cli_import_args()
        # Remove the timestamp argument and its value while retaining the other fields.
        timestamp_index = args.index("--exported-at")
        del args[timestamp_index:timestamp_index + 2]
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(args)
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(self.out_path.exists())


if __name__ == "__main__":
    unittest.main()
