import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from outputs.formfiller.calendar import CalendarError, load_calendar
from outputs.formfiller.calendar_xlsx import HEADERS, extract_days


def book(rows):
    class Book:
        sheetnames=['SchoolDays']
        def __getitem__(self,key):
            return SimpleNamespace(values=[HEADERS,*rows])
    return Book()


class WorkbookCalendarTests(unittest.TestCase):
    def test_early_release_is_instructional(self):
        days,early=extract_days(book([('2026-10-01','2026-10-01','Thursday','Instructional'),('2026-10-02','2026-10-02','Friday','Early release')]),'2026-10-01','2026-10-02')
        self.assertEqual(days,['2026-10-01','2026-10-02'])
        self.assertEqual(early,['2026-10-02'])

    def test_staff_only_row_is_not_silently_submitted(self):
        with self.assertRaises(CalendarError) as error:
            extract_days(book([('2026-10-01','2026-10-01','Thursday','Staff only')]),'2026-10-01','2026-10-01')
        self.assertEqual(error.exception.code,'workbook_day_type_changed')

    def test_weekend_and_duplicate_dates_are_rejected(self):
        for rows,code,start in [([('2026-10-03','2026-10-03','Saturday','Instructional')],'workbook_weekday_mismatch','2026-10-03'),([('2026-10-01','2026-10-01','Thursday','Instructional')]*2,'duplicate_date','2026-10-01')]:
            with self.assertRaises(CalendarError) as error:
                extract_days(book(rows),start,start)
            self.assertEqual(error.exception.code,code)

    def test_source_change_or_removal_blocks_calendar(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.xlsx'
            source.write_bytes(b'fixture-source')
            calendar=Path(folder)/'calendar.json'
            calendar.write_text(json.dumps(dict(schema_version=1,source='SchoolDays',approved=True,complete=True,coverage_start='2026-10-01',coverage_end='2026-10-03',exported_at_utc=datetime.now(timezone.utc).isoformat(),school_days=['2026-10-01'],non_school_days=[],source_kind='district_workbook',workbook_path=str(source),workbook_sha256=hashlib.sha256(source.read_bytes()).hexdigest())))
            self.assertTrue(load_calendar(calendar,'2026-10-01'))
            self.assertFalse(load_calendar(calendar,'2026-10-02'))
            source.write_bytes(b'changed-source')
            with self.assertRaises(CalendarError) as error:
                load_calendar(calendar,'2026-10-01')
            self.assertEqual(error.exception.code,'workbook_changed')
            source.unlink()
            with self.assertRaises(CalendarError) as error:
                load_calendar(calendar,'2026-10-01')
            self.assertEqual(error.exception.code,'workbook_unavailable')

    def test_synthetic_workbook_calendar_matches_its_covered_dates(self):
        start=date(2026,8,19)
        school_dates=[]
        current=start
        while len(school_dates)<171:
            if current.weekday()<5:
                school_dates.append(current)
            current+=timedelta(days=1)
        end=school_dates[-1]
        rows=[(day.isoformat(),day.isoformat(),day.strftime('%A'),
               'Early release' if i in (17,80) else 'Instructional')
              for i,day in enumerate(school_dates)]
        days,early=extract_days(book(rows),start.isoformat(),end.isoformat())
        self.assertEqual(len(days),171)
        self.assertEqual(len(early),2)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'synthetic-source.xlsx'
            source.write_bytes(b'fictional workbook fingerprint')
            exported=datetime.now(timezone.utc)
            calendar=root/'calendar.json'
            calendar.write_text(json.dumps(dict(
                schema_version=1,source='SchoolDays',approved=True,complete=True,
                coverage_start=start.isoformat(),coverage_end=end.isoformat(),
                exported_at_utc=exported.isoformat(),school_days=days,non_school_days=[],
                source_kind='district_workbook',workbook_path=str(source),
                workbook_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            )))
            class CalendarClock(datetime):
                @classmethod
                def now(cls,tz=None):
                    value=exported+timedelta(seconds=1)
                    return value.astimezone(tz) if tz else value.replace(tzinfo=None)
            allowed=set(days)
            with patch('outputs.formfiller.calendar.datetime',CalendarClock):
                current=start
                while current<=end:
                    self.assertEqual(load_calendar(calendar,current),current.isoformat() in allowed,current.isoformat())
                    current+=timedelta(days=1)


if __name__=='__main__':
    unittest.main()
