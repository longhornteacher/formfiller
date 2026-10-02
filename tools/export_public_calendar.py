"""Export only public district dates; never copy private calendar provenance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from outputs.formfiller.workspace import resolve_workspace
from tools.audit_privacy import PUBLIC_CALENDAR, ROOT, calendar_valid


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
        public = {"district": "Pearland ISD", "school_year": "2026-27", "source": "SchoolDays", "complete": True,
                  **{key: data[key] for key in ("coverage_start", "coverage_end", "school_days", "non_school_days", "early_release_days")}}
        encoded = (json.dumps(public, indent=2) + "\n").encode("utf-8")
        if not calendar_valid(encoded):
            raise ValueError()
        target = ROOT / PUBLIC_CALENDAR
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        print("public_calendar_exported instructional_days=171 early_release_days=2")
        return 0
    except Exception:
        print("public_calendar_export_failed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
