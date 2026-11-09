"""Regenerate the built-in calendar module from a reviewed private calendar.

Only dates are exported; provenance, paths, approvals, and timestamps never
leave the private workspace.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

from outputs.formfiller.workspace import resolve_workspace

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "outputs" / "formfiller" / "default_calendar.py"
HEADER = '''"""Built-in school-day calendar used when no private calendar has been imported.

This is public, date-only data: no names, sources, approvals or timestamps. A
private ``config/calendar.json`` always takes precedence. Dates outside the
coverage range are never treated as school days, so a run stops until a newer
version of the application (or a reviewed private calendar) covers the date.
Regenerate this module with ``python -m tools.export_public_calendar``.
"""
'''


def _tuple(name, values):
    rows = [", ".join(repr(value) for value in values[index:index + 6]) + "," for index in range(0, len(values), 6)]
    return f"{name} = (\n" + "\n".join("    " + row for row in rows) + "\n)\n"


def _iso(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError()
    date.fromisoformat(value)
    return value


def main():
    try:
        source = resolve_workspace(ROOT / "outputs").config_dir / "calendar.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        if (data.get("approved") is not True or data.get("complete") is not True
                or data.get("source") != "SchoolDays" or data.get("source_kind") != "district_workbook"):
            raise ValueError()
        with Path(data["workbook_path"]).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != data["workbook_sha256"]:
                raise ValueError()
        start, end = _iso(data["coverage_start"]), _iso(data["coverage_end"])
        school = [_iso(value) for value in data["school_days"]]
        early = [_iso(value) for value in data["early_release_days"]]
        if school != sorted(set(school)) or early != sorted(set(early)) or not set(early) <= set(school):
            raise ValueError()
        if not all(start <= value <= end for value in school):
            raise ValueError()
        year = f"{start[:4]}-{end[2:4]}"
        text = (HEADER + f"\nSCHOOL_YEAR = {year!r}\nCOVERAGE_START = {start!r}\nCOVERAGE_END = {end!r}\n\n"
                "# Every date in range that is not listed here is a non-school day.\n" + _tuple("SCHOOL_DAYS", school)
                + "\n# Subset of SCHOOL_DAYS that are early-release instructional days.\n" + _tuple("EARLY_RELEASE_DAYS", early))
        TARGET.write_text(text, encoding="utf-8", newline="\n")
        print(f"public_calendar_exported instructional_days={len(school)} early_release_days={len(early)}")
        return 0
    except Exception:
        print("public_calendar_export_failed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
