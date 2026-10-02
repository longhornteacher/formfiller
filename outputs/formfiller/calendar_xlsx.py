"""Import an explicitly approved district SchoolDays workbook read-only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from .calendar import CalendarError, _parse_date

HEADERS = ('Title', 'SchoolDate', 'DayOfWeek', 'DayType')
DAY_TYPES = {'Instructional', 'Early release'}


def extract_days(book, coverage_start, coverage_end):
    start = _parse_date(coverage_start, 'coverage_start')
    end = _parse_date(coverage_end, 'coverage_end')
    if start > end:
        raise CalendarError('invalid_coverage', 'Coverage start must not exceed end')
    if 'SchoolDays' not in book.sheetnames:
        raise CalendarError('workbook_schema_changed', 'SchoolDays sheet is missing')
    # Formulas and cached formula results are never accepted as date inputs.
    rows = iter(book['SchoolDays'].values)
    if tuple(next(rows, ())) != HEADERS:
        raise CalendarError('workbook_schema_changed', 'Expected Title, SchoolDate, DayOfWeek, DayType headers')
    days = set()
    early_release = []
    for row in rows:
        if all(value is None for value in row):
            continue
        if len(row) != len(HEADERS):
            raise CalendarError('workbook_schema_changed', 'Unexpected row width')
        title, raw_day, weekday, day_type = row
        if title != raw_day:
            raise CalendarError('workbook_date_mismatch', 'Title and SchoolDate must agree')
        day = _parse_date(raw_day, 'SchoolDate')
        if weekday != day.strftime('%A') or day.weekday() >= 5:
            raise CalendarError('workbook_weekday_mismatch', 'Expected a matching instructional weekday')
        if day_type not in DAY_TYPES:
            raise CalendarError('workbook_day_type_changed', 'Unexpected DayType; review the calendar before importing')
        if day in days:
            raise CalendarError('duplicate_date', 'Duplicate SchoolDate')
        if not start <= day <= end:
            raise CalendarError('outside_coverage', 'SchoolDate is outside the reviewed coverage')
        days.add(day)
        if day_type == 'Early release':
            early_release.append(day.isoformat())
    if not days or min(days) != start or max(days) != end:
        raise CalendarError('invalid_coverage', 'Reviewed coverage must match the first and last school date')
    return sorted(day.isoformat() for day in days), sorted(early_release)


def import_workbook(path, output, coverage_start, coverage_end, *, approved=False, complete=False):
    if approved is not True or complete is not True:
        raise CalendarError('unapproved', 'Confirm the workbook and complete coverage before importing')
    try:
        import openpyxl
    except ImportError:
        raise CalendarError('xlsx_dependency_missing', 'Run Setup.bat to install workbook support') from None
    path = Path(path).resolve()
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified > datetime.now(timezone.utc):
            raise CalendarError('future_export', 'Workbook modification time is in the future')
        book = openpyxl.load_workbook(path, read_only=True, data_only=False)
    except CalendarError:
        raise
    except Exception:
        raise CalendarError('workbook_unreadable', 'Could not read the district workbook') from None
    try:
        days, early_release = extract_days(book, coverage_start, coverage_end)
    finally:
        book.close()
    payload = dict(
        schema_version=1, source='SchoolDays', approved=True, complete=True,
        coverage_start=coverage_start, coverage_end=coverage_end,
        exported_at_utc=modified.isoformat().replace('+00:00', 'Z'),
        school_days=days, non_school_days=[],
        source_kind='district_workbook', workbook_path=str(path), workbook_sha256=digest,
        imported_at_utc=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        early_release_days=early_release,
    )
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.calendar-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(payload, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return len(days)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xlsx', required=True)
    parser.add_argument('--out', default='config/calendar.json')
    parser.add_argument('--coverage-start', required=True)
    parser.add_argument('--coverage-end', required=True)
    parser.add_argument('--approved', action='store_true', required=True)
    parser.add_argument('--complete', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        count = import_workbook(args.xlsx, args.out, args.coverage_start, args.coverage_end,
                                approved=args.approved, complete=args.complete)
        print(f'calendar_imported school_days={count}')
        return 0
    except CalendarError as exc:
        print(f'calendar_error code={exc.code}')
        return 2
    except Exception:
        print('calendar_error code=workbook_import_failed')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
