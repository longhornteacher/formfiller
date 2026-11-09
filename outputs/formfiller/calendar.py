"""Fail-closed school-day calendar loading and SchoolDays CSV import.

Calendar files are JSON objects with schema version 1 and these fields:

* ``source``: exactly ``"SchoolDays"``
* ``approved``: a human-approved boolean
* ``coverage_start`` / ``coverage_end``: inclusive ISO dates
* ``exported_at_utc``: an ISO-8601 timestamp with a UTC offset
* ``complete``: true only when the source export declares the range complete
* ``school_days`` / ``non_school_days``: sorted ISO-date lists of explicit rows

When ``complete`` is false, dates absent from both lists are unknown and raise
``CalendarError(code="missing_date")``. When true, absent dates within the
declared range are non-school days. Dates outside the declared range always
raise an error. The module uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SOURCE = "SchoolDays"
SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_DAYS = 14


class CalendarError(ValueError):
    """A calendar load/import failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _parse_date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        raise CalendarError("invalid_date", f"{field} must be a date, not a datetime")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise CalendarError("invalid_date", f"{field} must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise CalendarError("invalid_date", f"{field} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise CalendarError("invalid_date", f"{field} must use YYYY-MM-DD")
    return parsed


def _parse_exported_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise CalendarError("invalid_timestamp", "exported_at_utc must be an ISO-8601 UTC timestamp")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CalendarError("invalid_timestamp", "exported_at_utc must be an ISO-8601 UTC timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise CalendarError("invalid_timestamp", "exported_at_utc must include a UTC offset")
    return timestamp.astimezone(timezone.utc)


def _validate_date_list(value: Any, field: str, start: date, end: date) -> set[date]:
    if not isinstance(value, list):
        raise CalendarError("invalid_schema", f"{field} must be a list of ISO dates")
    dates: set[date] = set()
    for index, item in enumerate(value):
        parsed = _parse_date(item, f"{field}[{index}]")
        if parsed < start or parsed > end:
            raise CalendarError("invalid_schema", f"{field} contains a date outside coverage")
        if parsed in dates:
            raise CalendarError("invalid_schema", f"{field} contains a duplicate date")
        dates.add(parsed)
    if value != sorted(item.isoformat() for item in dates):
        raise CalendarError("invalid_schema", f"{field} must be sorted by date")
    return dates


def _load_document(path: str | os.PathLike[str]) -> dict[str, Any]:
    calendar_path = Path(path)
    try:
        with calendar_path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except FileNotFoundError as exc:
        raise CalendarError("missing_calendar", f"Calendar file not found: {calendar_path}") from exc
    except (OSError, UnicodeError) as exc:
        raise CalendarError("calendar_read_error", f"Could not read calendar file: {calendar_path}") from exc
    except json.JSONDecodeError as exc:
        raise CalendarError("invalid_json", "Calendar file is not valid JSON") from exc
    if not isinstance(document, dict):
        raise CalendarError("invalid_schema", "Calendar JSON must be an object")
    return document


def _validate_document(document: dict[str, Any]) -> tuple[date, date, set[date], set[date], bool, datetime]:
    if document.get("schema_version") != SCHEMA_VERSION:
        raise CalendarError("invalid_schema", f"schema_version must be {SCHEMA_VERSION}")
    if document.get("source") != SOURCE:
        raise CalendarError("wrong_source", f"Calendar source must be {SOURCE}")

    approved = document.get("approved")
    if not isinstance(approved, bool):
        raise CalendarError("invalid_schema", "approved must be a boolean")
    if not approved:
        raise CalendarError("unapproved", "Calendar has not been approved")

    try:
        start = _parse_date(document.get("coverage_start"), "coverage_start")
        end = _parse_date(document.get("coverage_end"), "coverage_end")
    except CalendarError as exc:
        raise CalendarError("invalid_coverage", str(exc)) from exc
    if end < start:
        raise CalendarError("invalid_coverage", "coverage_end must be on or after coverage_start")

    complete = document.get("complete")
    if not isinstance(complete, bool):
        raise CalendarError("invalid_schema", "complete must be a boolean")
    school_days = _validate_date_list(document.get("school_days"), "school_days", start, end)
    non_school_days = _validate_date_list(document.get("non_school_days"), "non_school_days", start, end)
    if school_days & non_school_days:
        raise CalendarError("invalid_schema", "school_days and non_school_days must be disjoint")
    exported_at = _parse_exported_at(document.get("exported_at_utc"))
    return start, end, school_days, non_school_days, complete, exported_at


def load_calendar(
    path: str | os.PathLike[str],
    today: date | str,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> bool:
    """Return whether ``today`` is a school day, failing closed on bad inputs.

    ``today`` is the caller's local calendar date. Export freshness is checked
    against the current UTC time and ``max_age_days`` is inclusive.
    """
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or max_age_days < 0:
        raise CalendarError("invalid_max_age", "max_age_days must be a non-negative integer")
    requested = _parse_date(today, "today")
    document = _load_document(path)
    start, end, school_days, non_school_days, complete, exported_at = _validate_document(document)

    if document.get('source_kind') == 'district_workbook':
        try:
            source_path = Path(document['workbook_path'])
            expected_digest = document['workbook_sha256']
            if not source_path.is_absolute() or not isinstance(expected_digest, str):
                raise CalendarError('invalid_schema', 'Invalid workbook provenance')
            actual_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except CalendarError:
            raise
        except Exception:
            raise CalendarError('workbook_unavailable', 'Approved district workbook is missing or unreadable') from None
        if actual_digest != expected_digest:
            raise CalendarError('workbook_changed', 'District workbook changed; review and re-import before running')

    now = datetime.now(timezone.utc)
    age = now - exported_at
    if age < timedelta(0):
        raise CalendarError("future_export", "Calendar export timestamp is in the future")
    if age > timedelta(days=max_age_days):
        raise CalendarError("stale_export", f"Calendar export is older than {max_age_days} days")
    if requested < start or requested > end:
        raise CalendarError("outside_coverage", f"{requested.isoformat()} is outside calendar coverage")
    if requested in school_days:
        return True
    if requested in non_school_days or complete:
        return False
    raise CalendarError("missing_date", f"No SchoolDays row covers {requested.isoformat()}")


def _default_calendar():
    try:
        from . import default_calendar as module
    except ImportError:  # pragma: no cover - flat-module fallback used by packaging
        import default_calendar as module  # type: ignore[no-redef]
    return module


def load_default_calendar(today: date | str) -> bool:
    """Return whether ``today`` is a school day in the built-in calendar.

    Fails closed: a date outside the built-in coverage raises
    ``CalendarError(code="outside_coverage")``.
    """
    requested = _parse_date(today, "today")
    module = _default_calendar()
    start = _parse_date(module.COVERAGE_START, "coverage_start")
    end = _parse_date(module.COVERAGE_END, "coverage_end")
    if requested < start or requested > end:
        raise CalendarError("outside_coverage", f"{requested.isoformat()} is outside calendar coverage")
    return requested.isoformat() in module.SCHOOL_DAYS


def default_calendar_summary() -> dict[str, Any]:
    """Coverage facts about the built-in calendar, with no provenance."""
    module = _default_calendar()
    return {"coverage_start": module.COVERAGE_START, "coverage_end": module.COVERAGE_END,
            "school_day_count": len(module.SCHOOL_DAYS)}


def load_calendar_or_default(
    path: str | os.PathLike[str],
    today: date | str,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> bool:
    """Use the private calendar at ``path``; fall back to the built-in one only if it is absent.

    A private calendar that exists but is stale, unapproved, changed or invalid
    still fails closed and is never silently replaced by the built-in one.
    """
    try:
        return load_calendar(path, today, max_age_days=max_age_days)
    except CalendarError as exc:
        if exc.code != "missing_calendar":
            raise
    return load_default_calendar(today)


def _parse_school_day(value: str, row_number: int) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise CalendarError("invalid_school_day", f"Invalid school-day value on CSV row {row_number}")


def _coerce_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CalendarError("invalid_timestamp", "now must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _coerce_export_timestamp(
    exported_at: datetime | str | None,
    now: datetime | None,
) -> datetime:
    """Resolve an explicit export timestamp; never make an old import fresh."""
    if exported_at is not None and now is not None:
        raise CalendarError("invalid_timestamp", "Pass exported_at or now, not both")
    if exported_at is None and now is None:
        raise CalendarError("export_timestamp_required", "An authentic export timestamp is required")
    if exported_at is not None:
        if isinstance(exported_at, datetime):
            value = exported_at.isoformat()
        else:
            value = exported_at
        timestamp = _parse_exported_at(value)
    else:
        timestamp = _coerce_utc(now)
    if timestamp > datetime.now(timezone.utc):
        raise CalendarError("future_export", "Export timestamp cannot be in the future")
    return timestamp


def import_csv(
    csv_path: str | os.PathLike[str],
    out_path: str | os.PathLike[str],
    date_column: str,
    school_day_column: str | None,
    coverage_start: date | str,
    coverage_end: date | str,
    approved: bool,
    now: datetime | None = None,
    *,
    complete: bool = False,
    dates_only: bool = False,
    exported_at: datetime | str | None = None,
) -> Path:
    """Import an explicitly mapped SchoolDays CSV into calendar JSON.

    The caller must provide the exact column names and inclusive coverage.
    ``complete=True`` is an explicit declaration that absent dates in this
    range are non-school days. The returned file records the authentic UTC
    export timestamp supplied as ``exported_at`` or the backward-compatible
    ``now`` argument. A timestamp is required so importing an old CSV cannot
    make it appear fresh. ``dates_only=True`` explicitly declares every listed
    date to be a school day and requires ``school_day_column=None``. CSV boolean
    cells accept only true/false, 1/0, or yes/no spellings.
    """
    if not isinstance(approved, bool):
        raise CalendarError("invalid_approval", "approved must be a boolean")
    if not isinstance(complete, bool):
        raise CalendarError("invalid_completeness", "complete must be a boolean")
    if not date_column or not isinstance(date_column, str):
        raise CalendarError("invalid_column", "date_column must be a non-empty column name")
    if not isinstance(dates_only, bool):
        raise CalendarError("invalid_column", "dates_only must be a boolean")
    if dates_only and school_day_column is not None:
        raise CalendarError("invalid_column", "school_day_column must be None when dates_only=True")
    if not dates_only and (not school_day_column or not isinstance(school_day_column, str)):
        raise CalendarError("invalid_column", "school_day_column is required unless dates_only=True")
    if school_day_column is not None and date_column == school_day_column:
        raise CalendarError("invalid_column", "date and school-day columns must differ")
    try:
        start = _parse_date(coverage_start, "coverage_start")
        end = _parse_date(coverage_end, "coverage_end")
    except CalendarError as exc:
        raise CalendarError("invalid_coverage", str(exc)) from exc
    if end < start:
        raise CalendarError("invalid_coverage", "coverage_end must be on or after coverage_start")
    timestamp = _coerce_export_timestamp(exported_at, now)

    csv_file = Path(csv_path)
    try:
        handle = csv_file.open("r", encoding="utf-8-sig", newline="")
    except FileNotFoundError as exc:
        raise CalendarError("missing_csv", f"CSV file not found: {csv_file}") from exc
    except (OSError, UnicodeError) as exc:
        raise CalendarError("csv_read_error", f"Could not read CSV file: {csv_file}") from exc

    school_days: set[date] = set()
    non_school_days: set[date] = set()
    with handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames
        if headers is None:
            raise CalendarError("missing_columns", "CSV has no header row")
        if len(headers) != len(set(headers)):
            raise CalendarError("duplicate_columns", "CSV contains duplicate column headers")
        if date_column not in headers or (school_day_column is not None and school_day_column not in headers):
            raise CalendarError("missing_columns", "CSV does not contain the named date and school-day columns")
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise CalendarError("invalid_row", f"CSV row {row_number} has more values than its header")
            raw_date = row.get(date_column)
            raw_school_day = row.get(school_day_column) if school_day_column is not None else None
            if raw_date is None or not raw_date.strip():
                raise CalendarError("invalid_date", f"CSV row {row_number} has no date")
            parsed = _parse_date(raw_date.strip(), f"CSV row {row_number} date")
            if parsed < start or parsed > end:
                raise CalendarError("outside_coverage", f"CSV row {row_number} is outside declared coverage")
            if parsed in school_days or parsed in non_school_days:
                raise CalendarError("duplicate_date", f"CSV contains duplicate date {parsed.isoformat()}")
            if not dates_only and raw_school_day is None:
                raise CalendarError("invalid_school_day", f"CSV row {row_number} has no school-day value")
            if dates_only or _parse_school_day(raw_school_day, row_number):
                school_days.add(parsed)
            else:
                non_school_days.add(parsed)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "approved": approved,
        "coverage_start": start.isoformat(),
        "coverage_end": end.isoformat(),
        "exported_at_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "complete": complete,
        "school_days": sorted(item.isoformat() for item in school_days),
        "non_school_days": sorted(item.isoformat() for item in non_school_days),
    }

    destination = Path(out_path)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, indent=2, ensure_ascii=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        raise CalendarError("calendar_write_error", f"Could not write calendar file: {destination}") from exc
    return destination


def _parse_cli_timestamp(value: str) -> datetime:
    try:
        return _parse_exported_at(value)
    except CalendarError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import and check the approved SchoolDays calendar.")
    commands = parser.add_subparsers(dest="command", required=True)

    importer = commands.add_parser("import", help="Import a SharePoint SchoolDays CSV")
    importer.add_argument("--csv", required=True, dest="csv_path", help="Path to the exported CSV")
    importer.add_argument("--date-column", required=True, help="Exact date column header")
    importer.add_argument(
        "--school-day-column",
        help="Exact boolean school-day column header; omit only with --dates-only",
    )
    importer.add_argument(
        "--dates-only",
        action="store_true",
        help="Treat every listed date as a school day (for exports containing only school dates)",
    )
    importer.add_argument("--coverage-start", required=True, help="Inclusive coverage start (YYYY-MM-DD)")
    importer.add_argument("--coverage-end", required=True, help="Inclusive coverage end (YYYY-MM-DD)")
    importer.add_argument(
        "--exported-at",
        required=True,
        type=_parse_cli_timestamp,
        help="Authentic UTC export time, for example 2026-10-01T15:00:00Z",
    )
    importer.add_argument("--approved", action="store_true", required=True, help="Confirm you reviewed this export")
    importer.add_argument(
        "--complete",
        action="store_true",
        help="Declare that the export fully covers the stated range; omitted dates then mean non-school days",
    )
    importer.add_argument("--out", required=True, help="Output calendar JSON path")

    checker = commands.add_parser("check", help="Check whether a date is a school day")
    checker.add_argument("--calendar", required=True, help="Path to calendar JSON")
    checker.add_argument("--date", required=True, help="Date as YYYY-MM-DD, or 'today'")
    checker.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            if args.dates_only == (args.school_day_column is not None):
                parser.error("choose exactly one of --dates-only or --school-day-column")
            if args.exported_at > datetime.now(timezone.utc):
                raise CalendarError("future_export", "--exported-at cannot be in the future")
            result = import_csv(
                csv_path=args.csv_path,
                out_path=args.out,
                date_column=args.date_column,
                school_day_column=args.school_day_column,
                coverage_start=args.coverage_start,
                coverage_end=args.coverage_end,
                approved=args.approved,
                exported_at=args.exported_at,
                complete=args.complete,
                dates_only=args.dates_only,
            )
            print(f"Calendar imported to {result}")
            return 0

        from zoneinfo import ZoneInfo
        requested = datetime.now(ZoneInfo("America/Chicago")).date() if args.date.casefold() == "today" else args.date
        is_school_day = load_calendar(args.calendar, requested, max_age_days=args.max_age_days)
        print("School day" if is_school_day else "Not a school day")
        return 0
    except CalendarError as exc:
        print(f"Calendar error [{exc.code}]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
