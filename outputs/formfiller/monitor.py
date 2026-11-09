"""Status-only local check for whether today's scheduled FormFiller run finished."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from . import scheduling
from .calendar import CalendarError, load_calendar, load_default_calendar
from .workspace import WorkspaceError, resolve_workspace


ROOT = Path(__file__).resolve().parents[1]
ALIASES = tuple(f"F{i:02d}" for i in range(1, 11))  # legacy fallback only
CHICAGO = ZoneInfo("America/Chicago")


class InputProblem(ValueError):
    pass


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputProblem(f"missing input: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputProblem(f"unreadable input: {path}") from exc
    if not isinstance(value, dict):
        raise InputProblem(f"invalid JSON object: {path}")
    return value


def read_status(path: Path, today: date, form_ids=None) -> dict[str, str]:
    data = read_json(path)
    if data.get("date") != today.isoformat() or not isinstance(data.get("forms"), dict):
        raise InputProblem("today's sanitized run state is invalid")
    forms = data["forms"]
    result: dict[str, str] = {}
    for form_id in (ALIASES if form_ids is None else form_ids):
        item = forms.get(form_id)
        if item is None:
            result[form_id] = "missing"
        elif isinstance(item, dict) and item.get("status") in {"pending", "submitting", "submitted", "failed", "uncertain"}:
            result[form_id] = item["status"]
        else:
            raise InputProblem("today's sanitized run state contains an invalid record")
    return result


def parse_args(argv=None) -> argparse.Namespace:
    paths = resolve_workspace(ROOT)
    parser = argparse.ArgumentParser(description="Check local run status using only calendar metadata and sanitized state.")
    parser.add_argument("--calendar", type=Path, default=paths.config_dir / "calendar.json")
    parser.add_argument("--forms", type=Path, default=paths.config_dir / "forms.json")
    parser.add_argument("--state-dir", type=Path, default=paths.state_dir)
    parser.add_argument("--after", type=time.fromisoformat, default=None, metavar="HH:MM",
                        help="local time (configured zone) after which a run is expected (default: end of submit window)")
    parser.add_argument("--max-calendar-age-days", type=int, default=14)
    parser.add_argument("--date", dest="date_override", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="date to inspect; defaults to today in America/Chicago")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    try:
        args = parse_args(argv)
    except WorkspaceError as exc:
        print(f"ERROR: code={exc.code}", file=sys.stderr)
        return 2
    if args.max_calendar_age_days < 0:
        print("ERROR: max calendar age must be non-negative", file=sys.stderr)
        return 2
    scheduling.apply_from_config(args.calendar.parent)
    after = args.after or time(scheduling.END // 60, scheduling.END % 60)
    today = args.date_override or scheduling.now().date()
    try:
        try:
            is_school_day = load_calendar(args.calendar, today, max_age_days=args.max_calendar_age_days)
        except CalendarError as exc:
            # Only an absent private calendar falls back to the built-in one.
            if getattr(exc, "code", None) != "missing_calendar":
                raise
            is_school_day = load_default_calendar(today)
        if not is_school_day:
            print(f"{today.isoformat()}: no run expected (not a listed instructional day)")
            return 0
        if scheduling.now().time().replace(tzinfo=None) < after and args.date_override is None:
            print(f"{today.isoformat()}: run not due yet; expected after {after.strftime('%H:%M')} {scheduling.ZONE_NAME}")
            return 0
        # Read only stable safe IDs and active flags; private names, URLs, and answers
        # are never displayed or used by the status checker.
        try:
            config = json.loads(args.forms.read_text(encoding="utf-8"))
            records = config.get("forms") if isinstance(config, dict) else None
            if not isinstance(records, list):
                raise ValueError
            active_records = [row for row in records
                              if isinstance(row, dict) and row.get("active", True) is True
                              and row.get("scheduled", True) is True]
            # Draft records do not participate in the daily run until a URL,
            # captured schema, and matching answers have all been configured.
            ready_records = [row for row in active_records
                             if isinstance(row.get("url"), str) and row.get("url")
                             and isinstance(row.get("schema"), dict)
                             and isinstance(row["schema"].get("questions"), list)
                             and bool(row["schema"]["questions"])
                             and isinstance(row.get("answers"), list)
                             and len(row["schema"]["questions"]) == len(row["answers"])]
            form_ids = [row.get("id", row.get("alias")) for row in ready_records]
            if any(not isinstance(value, str) for value in form_ids) or len(set(form_ids)) != len(form_ids):
                raise ValueError
        except FileNotFoundError:
            form_ids = ALIASES
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            raise InputProblem("private form index is invalid")
        status_path = args.state_dir / today.isoformat() / "state.json"
        if status_path.exists():
            statuses = read_status(status_path, today, form_ids)
        else:
            statuses = {form_id: "missing" for form_id in form_ids}
    except CalendarError as exc:
        print(f"ERROR: calendar code={exc.code}", file=sys.stderr)
        return 2
    except InputProblem as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    counts = {key: sum(status == key for status in statuses.values()) for key in
              ("submitted", "failed", "uncertain", "pending", "submitting", "missing")}
    print(
        f"{today.isoformat()}: expected={len(statuses)} submitted={counts['submitted']} failed={counts['failed']} "
        f"uncertain={counts['uncertain']} pending={counts['pending']} submitting={counts['submitting']} "
        f"missing={counts['missing']}"
    )
    if counts["submitted"] == len(statuses):
        print("status: complete")
        return 0
    print("status: incomplete; inspect Forms and the local runner state before considering any retry")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
