"""Loopback-only local UI. Demo is the default and never uses private data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from .browser import BrowserError, BrowserSession, answer_plan
from .calendar import CalendarError, load_calendar
from .runner import _config_fingerprint, _schema_fingerprint, _remember_submission
from .skyward import (MARKS, SkywardSession, demo_courses, demo_roster, load_config, staged_counts,
                      suggest_mark)
from .state import StateError, StateStore, _atomic_json
from . import scheduling, taskplan

SAFE_CODE = re.compile(r"^[a-z0-9_]{1,64}$")
STATUSES = ("submitted", "failed", "uncertain", "submitting", "pending", "missing")
STATIC_ROOT = Path(__file__).parent / "web_static"


class WebError(Exception):
    def __init__(self, code, status=400):
        self.code = code if SAFE_CODE.fullmatch(code) else "request_failed"
        self.status = status
        super().__init__(self.code)


def today():
    return datetime.now(ZoneInfo("America/Chicago")).date()


def read_json(path, code="data_unavailable"):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise WebError(code) from None


def normalized_schema(schema):
    fields = []
    for index, question in enumerate((schema or {}).get("questions", [])):
        controls = question.get("controls", [])
        kinds = {control.get("kind") for control in controls}
        if any(control.get("matrix") for control in controls):
            kind = "matrix"
        elif kinds == {"radio"}:
            kind = "choice"
        elif kinds == {"checkbox"}:
            kind = "multichoice"
        elif kinds == {"combobox"}:
            kind = "date"
        elif len(controls) == 1 and kinds <= {"input", "text", "textarea"}:
            kind = "text"
        else:
            kind = "unsupported"
        fields.append({"id": f"q{index}", "label": question.get("title", ""),
                       "type": kind, "required": bool(question.get("required")),
                       "options": [control.get("label", "") for control in controls
                                   if control.get("kind") in ("radio", "checkbox")]})
    return {"fields": fields, "questions": fields}


def normalized_answers(answers):
    result = {}
    for index, answer in enumerate(answers or []):
        if answer.get("kind") == "radio":
            result[f"q{index}"] = (answer.get("values") or [""])[0]
        elif answer.get("kind") in ("checkbox", "matrix"):
            result[f"q{index}"] = answer.get("values", [])
        elif answer.get("kind") == "date":
            result[f"q{index}"] = {"kind": "date"}
        else:
            result[f"q{index}"] = answer.get("value", "")
    return result


def runner_answers(schema, values):
    if not isinstance(values, dict):
        raise WebError("answers_invalid")
    answers = []
    for field in normalized_schema(schema)["fields"]:
        value = values.get(field["id"], "")
        kind = field["type"]
        if kind != "date" and not field["required"] and (value == "" or value == []):
            answers.append({"kind": "skip"})
        elif kind == "text" and isinstance(value, str):
            if field["required"] and not value.strip():
                raise WebError("required_answer_missing")
            answers.append({"kind": "text", "value": value})
        elif kind == "date":
            answers.append({"kind": "date"})
        elif kind in ("choice", "multichoice", "matrix"):
            selected = [value] if isinstance(value, str) and value else value
            if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
                raise WebError("answers_invalid")
            answers.append({"kind": {"choice": "radio", "multichoice": "checkbox", "matrix": "matrix"}[kind], "values": selected})
        else:
            raise WebError("field_type_unsupported")
    try:
        answer_plan({"schema": schema, "answers": answers}, today())
    except (BrowserError, KeyError, TypeError, ValueError):
        raise WebError("answers_invalid") from None
    return answers


def sample_schema():
    return {"questions": [
        {"title": "Example text", "required": True,
         "controls": [{"kind": "text", "label": "Example text", "matrix": False}]},
        {"title": "Example choice", "required": True,
         "controls": [{"kind": "radio", "label": option, "matrix": False} for option in ("Option A", "Option B")]},
        {"title": "Run date", "required": True,
         "controls": [{"kind": "combobox", "label": "Run date", "matrix": False}]},
    ]}


def initialize_demo(config_dir, state_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    schema = sample_schema()
    forms = [{"alias": f"F{index:02}", "id": f"F{index:02}", "name": f"Example form {index}",
              "url": f"https://forms.office.com/Pages/ResponsePage.aspx?id=synthetic-{index}",
              "schema": schema, "answers": [{"kind": "text", "value": "Example answer"},
              {"kind": "radio", "values": ["Option A"]}, {"kind": "date"}]} for index in range(1, 5)]
    (config_dir / "forms.json").write_text(json.dumps({"forms": forms}), encoding="utf-8")
    (config_dir / "settings.json").write_text(json.dumps({"live_enabled": False}), encoding="utf-8")
    day = today()
    calendar = {"schema_version": 1, "source": "SchoolDays", "approved": True,
                "coverage_start": day.isoformat(), "coverage_end": day.isoformat(),
                "complete": True, "school_days": [day.isoformat()], "non_school_days": [],
                "exported_at_utc": datetime.now(timezone.utc).isoformat()}
    (config_dir / "calendar.json").write_text(json.dumps(calendar), encoding="utf-8")
    store = StateStore(state_dir, day)
    for form in forms:
        store.record_schema(form["alias"], _schema_fingerprint(schema))
        store.record_schema(form["alias"], _schema_fingerprint(schema), approved=True,
                            config_fingerprint=_config_fingerprint(form))
        _atomic_json(state_dir / "checks" / f'{form["alias"]}.json', {"checked_on": day.isoformat()})
    # One synthetic form shows how a change on the live form is surfaced.
    _atomic_json(state_dir / "changes" / "F04.json", {"code": "schema_options_updated"})


def verify_installation(root):
    """A deployment snapshot avoids silently executing edits from development."""
    from .deployment import validate_snapshot
    validate_snapshot(root, current_file=__file__)


def external_paths(workspace, runtime, installed):
    workspace, runtime, installed = map(lambda item: Path(item).resolve(), (workspace, runtime, installed))
    source = Path(read_json(installed / "install-manifest.json")["source_root"]).resolve()
    for private in (workspace, runtime):
        if any(private.is_relative_to(code) or code.is_relative_to(private) for code in (installed, source)):
            raise WebError("external_workspace_required")
        if any(part.is_symlink() or part.is_junction() for part in (private, *private.parents)):
            raise WebError("workspace_link_not_allowed")
    if workspace.is_relative_to(runtime) or runtime.is_relative_to(workspace):
        raise WebError("runtime_must_not_sync")


class WebApp:
    def __init__(self, config_dir, state_dir, profile_dir, *, mode="demo", installed_root=None, needs_setup=False):
        from .store import FormStore
        if mode not in ("demo", "private"):
            raise WebError("mode_invalid")
        self.config_dir, self.state_dir, self.profile_dir = map(Path, (config_dir, state_dir, profile_dir))
        self.mode = mode
        self.installed_root = Path(installed_root) if installed_root else None
        self.token = secrets.token_urlsafe(32)
        self.store = FormStore(self.config_dir)
        self.operation = threading.Lock()
        self.signin_process = None
        self.inspections = {}
        self.needs_setup = needs_setup
        # Student names stay in memory only; nothing here is persisted.
        self.roster, self.marks, self.attendance_date, self.attendance_submitted = [], {}, None, False
        self.course_id = None

    @contextmanager
    def editing(self):
        if not self.operation.acquire(blocking=False):
            raise WebError("operation_in_progress", 409)
        try:
            with StateStore(self.state_dir, today()).lock():
                yield
        finally:
            self.operation.release()

    def settings(self):
        settings = read_json(self.config_dir / "settings.json", "settings_unavailable")
        if not isinstance(settings, dict):
            raise WebError("settings_invalid")
        return settings

    def calendar(self):
        settings = self.settings()
        configured = Path(settings.get("calendar_path", "calendar.json"))
        path = configured if configured.is_absolute() else self.config_dir / configured
        try:
            return load_calendar(path, today(), max_age_days=settings.get("max_calendar_age_days", 14))
        except CalendarError as exc:
            raise WebError(exc.code) from None

    def calendar_summary(self):
        """Summarize a validated calendar without returning its provenance or paths."""
        try:
            settings = self.settings()
            configured = Path(settings.get("calendar_path", "calendar.json"))
            path = configured if configured.is_absolute() else self.config_dir / configured
            document = read_json(path, "calendar_unavailable")
            from .calendar import _validate_document
            start, end, school_days, _non_school_days, _complete, _exported_at = _validate_document(document)
            # Validate freshness and any approved workbook provenance before reporting coverage.
            load_calendar(path, start, max_age_days=settings.get("max_calendar_age_days", 14))
            return {"coverage_start": start.isoformat(), "coverage_end": end.isoformat(),
                    "school_day_count": len(school_days)}
        except (WebError, CalendarError, TypeError, ValueError, OSError):
            return None

    def forms(self):
        if self.needs_setup:
            return []
        return [self.form(item["id"]) for item in self.store.list_forms()]

    def form(self, form_id):
        form = self.store.get_form(form_id)
        seed, answer_source = self.store.submission_seed(form)
        state = StateStore(self.state_dir, today())
        configured = bool(form.get("url") and form.get("schema") and form.get("answers"))
        approved = configured and state.schema_approved(form["alias"], _schema_fingerprint(form["schema"]), _config_fingerprint(form))
        change = state._read_json(state.root / "changes" / f"{form_id}.json", {})
        check = state._read_json(state.root / "checks" / f"{form_id}.json", {})
        checked_on = check.get("checked_on") if isinstance(check, dict) else None
        if not (isinstance(checked_on, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", checked_on)):
            checked_on = None
        record = state.read(form_id) or {}
        daily_plan = state._read_json(state.day_dir / "schedule.json", {"claimed": []})
        claimed = form_id in daily_plan.get("claimed", [])
        return {"id": form["id"], "name": form["name"], "url": form.get("url", ""),
                "schema": normalized_schema(form.get("schema")), "answers": normalized_answers(seed.get("answers")),
                "answer_source": answer_source,
                "last_submitted_on": (form.get("last_submission") or {}).get("date"),
                "review_required": not approved, "configured": configured,
                "scheduled": scheduling.enabled(form), "change_code": change.get("code"),
                "freshness": {"state": "changed" if change.get("code") else "current",
                              "checked_on": checked_on},
                "today_status": record.get("status", "pending"),
                "can_submit": bool(approved and record.get("status", "pending") == "pending" and not claimed),
                "review_token": _config_fingerprint(form) if configured else None}

    def status(self):
        items = []
        state = StateStore(self.state_dir, today())
        schedule = {"slots": {}, "claimed": []}
        schedule_code = None
        try:
            if self.calendar():
                with self.editing():
                    forms = [self.store.get_form(item["id"]) for item in self.store.list_forms()]
                    schedule = scheduling.plan(state, forms, scheduling.now())
            else:
                schedule_code = "not_school_day"
        except (WebError, StateError) as exc:
            schedule_code = exc.code
        for form in self.forms():
            record = state.read(form["id"]) or {}
            status = record.get("status", "pending")
            if status not in STATUSES:
                raise WebError("state_invalid")
            items.append({"id": form["id"], "name": form["name"], "status": status,
                          "scheduled": form["scheduled"],
                          "scheduled_time": (f'{schedule["slots"][form["id"]] // 60:02}:{schedule["slots"][form["id"]] % 60:02}'
                                             if form["scheduled"] and form["id"] in schedule["slots"] else None),
                          "schedule_claimed": form["id"] in schedule["claimed"],
                          "change_code": form["change_code"], "freshness": form["freshness"],
                          "review_required": form["review_required"]})
        counts = {status: sum(item["status"] == status for item in items) for status in STATUSES}
        checks = self.readiness()
        scheduled_items = [item for item in items if item["scheduled"]]
        can_run = bool(scheduled_items) and not any(item["review_required"] for item in scheduled_items)
        can_run = can_run and not any(item["status"] in ("failed", "uncertain", "submitting") or item["schedule_claimed"] for item in scheduled_items if item["status"] != "submitted")
        can_run = can_run and not all(item["status"] == "submitted" for item in scheduled_items)
        if self.mode == "private":
            can_run = can_run and checks["ready"]
        return {"date": today().isoformat(), "items": items, "counts": counts, "expected": len(items),
                "mode": self.mode, "can_run": can_run, "schedule_code": schedule_code,
                "schedule_window": "12:00–15:30 America/Chicago"}

    def history(self):
        items = []
        if self.state_dir.exists():
            for directory in sorted(self.state_dir.iterdir(), reverse=True):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", directory.name):
                    continue
                try:
                    data = read_json(directory / "state.json", "state_unavailable")
                    records = data.get("forms", {})
                    if not isinstance(records, dict):
                        raise WebError("state_invalid")
                    counts = {status: sum(isinstance(record, dict) and record.get("status") == status for record in records.values()) for status in STATUSES}
                    items.append({"date": directory.name, "counts": counts})
                except WebError:
                    items.append({"date": directory.name, "code": "state_unavailable", "counts": {}})
        return {"items": items}

    def readiness(self):
        if self.needs_setup:
            return {"items": [{"label": "Private workspace", "status": "blocked", "code": "workspace_required"}],
                    "ready": False, "mode": self.mode}
        items = []
        try:
            enabled = self.settings().get("live_enabled") is True
            items.append({"label": "Live mode", "status": "demo" if self.mode == "demo" else "ready" if enabled else "blocked",
                          "code": "demo_only" if self.mode == "demo" else "live_enabled" if enabled else "live_disabled"})
        except WebError as exc:
            items.append({"label": "Live mode", "status": "blocked", "code": exc.code})
        try:
            instructional = self.calendar()
            items.append({"label": "District calendar", "status": "ready" if instructional else "skipped",
                          "code": "instructional_date" if instructional else "non_school_day"})
        except WebError as exc:
            items.append({"label": "District calendar", "status": "blocked", "code": exc.code})
        forms = [form for form in self.forms() if form["scheduled"]]
        reviewed = bool(forms) and all(not form["review_required"] for form in forms)
        items.append({"label": "Form schemas", "status": "ready" if reviewed else "blocked",
                      "code": "schemas_reviewed" if reviewed else "schema_review_required"})
        items.append({"label": "Dedicated Edge sign-in", "status": "unknown",
                      "code": "verified_by_runner"})
        locked = (self.state_dir / ".runner.lock").exists()
        items.append({"label": "Runner", "status": "blocked" if locked else "ready",
                      "code": "run_locked" if locked else "idle"})
        if self.mode == "private":
            from .ownership import verify_runtime_owner
            try:
                verify_runtime_owner(self.config_dir.parent, self.state_dir.parent)
                items.append({"label": "Runner device", "status": "ready", "code": "runtime_owner_verified"})
            except Exception as exc:
                code = getattr(exc, "code", "runtime_owner_invalid")
                items.append({"label": "Runner device", "status": "blocked", "code": code})
        return {"items": items, "ready": not any(item["status"] in ("blocked", "skipped") for item in items),
                "mode": self.mode, "calendar_summary": self.calendar_summary()}

    def sync(self):
        checks = self.readiness()["items"]
        return {"items": [item for item in checks if item["label"] in ("District calendar", "Form schemas")],
                "checked_at": datetime.now(timezone.utc).isoformat(), "applied": False}

    def inspect(self, payload):
        if self.needs_setup:
            raise WebError("workspace_required", 409)
        url = payload.get("url")
        if not isinstance(url, str):
            raise WebError("form_url_invalid")
        BrowserSession._validate_url(url)
        with self.editing():
            if self.mode == "demo":
                schema = sample_schema()
            else:
                self.calendar()  # Missing, changed, stale, or uncovered dates stop before Edge opens.
                settings = self.settings()
                settings["browser_profile_path"] = str(self.profile_dir.resolve())
                with BrowserSession(settings) as browser:
                    schema = browser.inspect({"alias": "inspection", "url": url})
            token = secrets.token_urlsafe(24)
            self.inspections[token] = (time.monotonic() + 600, url, schema)
        answers = {}
        if payload.get("form_id"):
            original = self.store.get_form(payload["form_id"])
            if original.get("url") == url:
                seed, _ = self.store.submission_seed(original, exact_schema=False)
                old_questions = (seed.get("schema") or {}).get("questions", [])
                old_answers = normalized_answers(seed.get("answers"))
                titles = [q.get("title") for q in old_questions]
                new_fields = normalized_schema(schema)["fields"]
                for index, field in enumerate(new_fields):
                    title = schema["questions"][index]["title"]
                    if titles.count(title) != 1:
                        continue
                    value = old_answers.get(f"q{titles.index(title)}", "")
                    if field["type"] in ("choice", "multichoice", "matrix"):
                        value = ([v for v in value if v in field["options"]] if isinstance(value, list)
                                 else value if value in field["options"] else "")
                    answers[field["id"]] = value
        return {"schema": normalized_schema(schema), "answers": answers,
                "inspect_token": token, "review_required": True}

    def schedule_form(self, form_id, payload):
        if type(payload.get("scheduled")) is not bool:
            raise WebError("invalid_schedule")
        with self.editing():
            form = self.store.get_form(form_id)
            if payload["scheduled"] and self.form(form_id)["review_required"]:
                raise WebError("review_answers_before_scheduling", 409)
            token = payload.get("review_token")
            if payload["scheduled"] and (not isinstance(token, str) or not secrets.compare_digest(token, _config_fingerprint(form))):
                raise WebError("review_changed_refresh_required", 409)
            self.store.update_form(form_id, {"scheduled": payload["scheduled"]})
        self.sync_tasks()
        return self.form(form_id)

    def sync_tasks(self):
        """Refresh today's one-shot tasks after a schedule change; never blocks the edit."""
        if self.mode != "private" or self.needs_setup:
            return None
        return taskplan.sync_for_ui(self.config_dir, self.state_dir)

    def mutate_form(self, payload, form_id=None):
        if self.needs_setup:
            raise WebError("workspace_required", 409)
        if not isinstance(payload, dict):
            raise WebError("request_invalid")
        with self.editing():
            existing = self.store.get_form(form_id) if form_id else None
            url = payload.get("url", existing.get("url", "") if existing else "")
            name = payload.get("name", existing["name"] if existing else "")
            schema = existing.get("schema") if existing else None
            if existing and url != existing.get("url"):
                schema = None
            token = payload.get("inspect_token")
            if token:
                inspected = self.inspections.get(token)
                if not inspected or inspected[0] < time.monotonic() or inspected[1] != url:
                    raise WebError("inspection_expired")
                schema = inspected[2]
            answers = existing.get("answers") if existing and schema is not None else []
            if "answers" in payload and schema:
                answers = runner_answers(schema, payload["answers"])
            fields = {"url": url, "schema": schema, "answers": answers}
            if existing:
                self.store.update_form(form_id, {"name": name, **fields})
                created = {"id": form_id}
            else:
                created = self.store.create_form(name, fields)
            saved = self.store.get_form(created["id"])
            if saved.get("schema") and not StateStore(self.state_dir, today()).schema_approved(
                    saved["alias"], _schema_fingerprint(saved["schema"]), _config_fingerprint(saved)):
                StateStore(self.state_dir, today()).record_schema(saved["alias"], _schema_fingerprint(saved["schema"]))
            if token:
                # The questions were just read from the live form, so it is current as of today.
                (self.state_dir / "changes" / f'{saved["alias"]}.json').unlink(missing_ok=True)
                _atomic_json(self.state_dir / "checks" / f'{saved["alias"]}.json', {"checked_on": today().isoformat()})
        return self.form(created["id"])

    def approve_form(self, form_id, payload):
        """Record an explicit human review of exactly the currently saved answers."""
        if self.needs_setup:
            raise WebError("workspace_required", 409)
        with self.editing():
            form = self.store.get_form(form_id)
            if not form.get("schema") or not form.get("answers"):
                raise WebError("form_not_configured", 409)
            fingerprint = _config_fingerprint(form)
            token = payload.get("review_token")
            if not isinstance(token, str) or not secrets.compare_digest(token, fingerprint):
                raise WebError("review_changed_refresh_required", 409)
            runner_answers(form["schema"], normalized_answers(form["answers"]))
            StateStore(self.state_dir, today()).record_schema(form["alias"], _schema_fingerprint(form["schema"]),
                approved=True, config_fingerprint=fingerprint)
        return self.form(form_id)

    def _attendance_current(self):
        if self.attendance_date != today():
            self.roster, self.marks, self.attendance_submitted, self.course_id = [], {}, False, None
            self.attendance_date = today()

    def skyward_config(self):
        if self.mode == "demo":
            return {"login_url": "", "host": "", "courses": demo_courses()}
        try:
            return load_config(read_json(self.config_dir / "skyward.json", "skyward_not_configured"))
        except BrowserError as exc:
            code = "skyward_url_invalid" if exc.code == "SKYWARD_URL_INVALID" else "skyward_config_invalid"
            raise WebError(code) from None

    def skyward_settings(self):
        """Return the editor model without exposing paths or private file errors."""
        if self.mode == "demo":
            return {"mode": "demo", "editable": False, "configured": True,
                    "config": self.skyward_config()}
        if self.needs_setup:
            raise WebError("workspace_required", 409)
        path = self.config_dir / "skyward.json"
        if not path.exists():
            return {"mode": "private", "editable": True, "configured": False,
                    "config": {"login_url": "", "host": "", "courses": []}}
        return {"mode": "private", "editable": True, "configured": True,
                "config": self.skyward_config()}

    def replace_skyward_config(self, payload):
        """Replace the complete, validated course list in the selected private workspace."""
        if self.mode != "private":
            raise WebError("demo_config_read_only", 409)
        if self.needs_setup:
            raise WebError("workspace_required", 409)
        if not isinstance(payload, dict) or set(payload) != {"login_url", "courses"}:
            raise WebError("skyward_config_invalid")
        courses = payload.get("courses")
        if not isinstance(courses, list) or any(not isinstance(course, dict)
                or not set(course) <= {"id", "name", "period"} for course in courses):
            raise WebError("skyward_config_invalid")
        try:
            validated = load_config(payload)
        except BrowserError as exc:
            code = "skyward_url_invalid" if exc.code == "SKYWARD_URL_INVALID" else "skyward_config_invalid"
            raise WebError(code) from None
        # Store only the canonical configuration, never any supplied path or extra field.
        from .state import _atomic_json
        with self.editing():
            try:
                _atomic_json(self.config_dir / "skyward.json", {
                    "login_url": validated["login_url"], "courses": validated["courses"]})
            except Exception:
                raise WebError("skyward_config_save_failed", 500) from None
        return self.skyward_settings()

    def attendance(self):
        empty = {"date": today().isoformat(), "mode": self.mode, "loaded": False, "students": [], "courses": [],
                 "course": None, "counts": {mark: 0 for mark in MARKS}, "submitted": False}
        if self.needs_setup:
            return {**empty, "needs_setup": True}
        self._attendance_current()
        try:
            courses = [{"id": c["id"], "name": c["name"], "period": c["period"]} for c in self.skyward_config()["courses"]]
        except WebError:
            courses = []
        students = [{"id": s["id"], "name": s["name"], "details": s["details"], "suggested": s["suggested"],
                     "mark": self.marks.get(s["id"], "present")} for s in self.roster]
        return {**empty, "loaded": bool(self.roster), "students": students, "courses": courses,
                "course": self.course_id, "counts": staged_counts(self.roster, self.marks),
                "submitted": self.attendance_submitted}

    def load_roster(self, payload):
        if self.needs_setup:
            raise WebError("workspace_required", 409)
        course_id = payload.get("course")
        if not isinstance(course_id, str):
            raise WebError("course_required")
        with self.editing():
            self._attendance_current()
            if self.attendance_submitted:
                raise WebError("attendance_already_submitted", 409)
            config = self.skyward_config()
            if course_id not in {c["id"] for c in config["courses"]}:
                raise WebError("skyward_course_unknown")
            if self.mode == "demo":
                roster = demo_roster(today())
            else:
                self.calendar()  # Non-instructional or stale dates stop before Edge opens.
                settings = self.settings()
                settings["browser_profile_path"] = str(self.profile_dir.resolve())
                with SkywardSession(settings) as browser:
                    roster = browser.read_roster(config, course_id)
            self.roster = [{"id": f"s{index}", **student, "suggested": suggest_mark(student["details"], today())}
                           for index, student in enumerate(roster)]
            # The J rule pre-marks absences; the teacher reviews and can change any mark.
            self.marks = {s["id"]: "absent" for s in self.roster if s["suggested"] == "absent"}
            self.course_id = course_id
        return self.attendance()

    def set_marks(self, payload):
        marks = payload.get("marks")
        if not isinstance(marks, dict):
            raise WebError("marks_invalid")
        with self.editing():
            self._attendance_current()
            if self.attendance_submitted:
                raise WebError("attendance_already_submitted", 409)
            known = {student["id"] for student in self.roster}
            if not set(marks) <= known or not all(value in MARKS for value in marks.values()):
                raise WebError("marks_invalid")
            self.marks = {key: value for key, value in marks.items() if value != "present"}
        return self.attendance()

    def submit_attendance(self):
        if self.mode != "demo":
            raise WebError("attendance_posting_unavailable", 409)
        with self.editing():
            self._attendance_current()
            if not self.roster:
                raise WebError("roster_required", 409)
            if self.attendance_submitted:
                raise WebError("attendance_already_submitted", 409)
            self.attendance_submitted = True
        return self.attendance()

    def submit_form(self, form_id):
        """Explicit submission of one reviewed form, independent of enrollment."""
        if self.needs_setup:
            raise WebError("workspace_required", 409)
        if not self.operation.acquire(blocking=False):
            raise WebError("operation_in_progress", 409)
        try:
            state = StateStore(self.state_dir, today())
            with state.lock():
                view = self.form(form_id)
                if view["today_status"] == "submitted":
                    raise WebError("already_submitted", 409)
                if view["review_required"]:
                    raise WebError("review_answers_before_submitting", 409)
                if not view["can_submit"]:
                    raise WebError("manual_review_required", 409)
                if self.mode == "demo":
                    form = self.store.get_form(form_id)
                    fingerprint = _config_fingerprint(form)
                    state.bind_config(form_id, fingerprint)
                    state.transition(form_id, "pending", "submitting")
                    state.transition(form_id, "submitting", "submitted")
                    _remember_submission(self.config_dir, form, today(), fingerprint)
                    return {"submitted": True, "mode": self.mode, "form": self.form(form_id)}
            if not self.installed_root:
                raise WebError("installed_snapshot_required", 403)
            verify_installation(self.installed_root)
            environment = os.environ.copy()
            environment.update({"FORM_FILLER_WORKSPACE": str(self.config_dir.parent.resolve()),
                                "FORM_FILLER_RUNTIME": str(self.state_dir.parent.resolve()),
                                "PYTHONDONTWRITEBYTECODE": "1"})
            try:
                result = subprocess.run([sys.executable, "-m", "formfiller.runner", "--live", "--form", form_id],
                    cwd=self.installed_root, env=environment, capture_output=True, timeout=1800)
            except subprocess.TimeoutExpired:
                raise WebError("run_outcome_requires_review", 409) from None
            if result.returncode != 0:
                codes = re.findall(r"(?:^|\s)code=([a-z0-9_]{1,48})(?=\s|$)", result.stdout.decode("utf-8", errors="replace"))
                raise WebError(codes[-1] if codes else "form_submission_blocked", 409)
            record = state.read(form_id) or {}
            if record.get("status") != "submitted":
                raise WebError("submission_not_confirmed", 409)
            return {"submitted": True, "mode": self.mode, "form": self.form(form_id)}
        finally:
            self.operation.release()

    def run_once(self):
        if self.needs_setup:
            raise WebError("workspace_required", 409)
        if not self.operation.acquire(blocking=False):
            raise WebError("operation_in_progress", 409)
        try:
            if self.mode == "demo":
                with StateStore(self.state_dir, today()).lock():
                    for item in (form for form in self.forms() if form["scheduled"]):
                        if item["review_required"]:
                            raise WebError("schema_review_required", 409)
                    state = StateStore(self.state_dir, today())
                    for item in (form for form in self.forms() if form["scheduled"]):
                        record = state.bind_config(item["id"], _config_fingerprint(self.store.get_form(item["id"])))
                        if record["status"] == "submitted":
                            continue
                        if record["status"] != "pending":
                            raise WebError("manual_review_required", 409)
                        state.transition(item["id"], "pending", "submitting")
                        state.transition(item["id"], "submitting", "submitted")
                        _remember_submission(self.config_dir, self.store.get_form(item["id"]), today(), record["config"])
                return {"exit_code": 0, "mode": "demo", **self.status()}
            if not self.installed_root:
                raise WebError("installed_snapshot_required", 403)
            verify_installation(self.installed_root)
            environment = os.environ.copy()
            environment["FORM_FILLER_WORKSPACE"] = str(self.config_dir.parent.resolve())
            environment["FORM_FILLER_RUNTIME"] = str(self.state_dir.parent.resolve())
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            try:
                result = subprocess.run([sys.executable, "-m", "formfiller.run_and_check"],
                    cwd=self.installed_root, env=environment, capture_output=True, timeout=1800)
            except subprocess.TimeoutExpired:
                raise WebError("run_outcome_requires_review", 409) from None
            return {"exit_code": result.returncode, "mode": "private", **self.status()}
        finally:
            self.operation.release()

    def start_sign_in(self, payload):
        """Open the installed runner's manual sign-in flow for a saved form.

        Launching the browser is only a user action; readiness stays unverified
        until the runner later checks access while opening the form.
        """
        if self.mode != "private" or self.needs_setup:
            raise WebError("sign_in_unavailable", 409)
        if not isinstance(payload, dict) or set(payload) != {"form_id"} or not isinstance(payload["form_id"], str):
            raise WebError("request_invalid")
        if not self.installed_root:
            raise WebError("installed_snapshot_required", 403)
        if os.name != "nt" or not hasattr(subprocess, "CREATE_NEW_CONSOLE"):
            raise WebError("sign_in_unavailable", 409)
        with self.editing():
            verify_installation(self.installed_root)
            try:
                form = self.store.get_form(payload["form_id"])
            except Exception:
                raise WebError("form_not_configured", 409) from None
            if not isinstance(form.get("url"), str) or not form.get("url"):
                raise WebError("form_not_configured", 409)
            if self.signin_process is not None and self.signin_process.poll() is None:
                return {"started": True, "already_open": True, "verified": False}
            environment = os.environ.copy()
            environment["FORM_FILLER_WORKSPACE"] = str(self.config_dir.parent.resolve())
            environment["FORM_FILLER_RUNTIME"] = str(self.state_dir.parent.resolve())
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            try:
                self.signin_process = subprocess.Popen(
                    [sys.executable, "-m", "formfiller.runner", "--login", form["alias"]],
                    cwd=self.installed_root, env=environment,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    close_fds=True,
                )
            except Exception:
                self.signin_process = None
                raise WebError("sign_in_unavailable", 409) from None
        return {"started": True, "already_open": False, "verified": False}

    def choose_workspace(self):
        """A human picks a folder in the installed app; API never accepts paths."""
        if self.mode != "private" or not self.needs_setup:
            raise WebError("workspace_selection_unavailable", 409)
        with self.editing():
            return self._choose_workspace()

    def _choose_workspace(self):
        import tkinter
        from tkinter import filedialog
        window = tkinter.Tk()
        window.withdraw()
        window.attributes("-topmost", True)
        try:
            chosen = filedialog.askdirectory(parent=window, title="Choose your private FormFiller workspace", mustexist=True)
        finally:
            window.destroy()
        if not chosen:
            return {"cancelled": True, "needs_setup": True}
        workspace = Path(chosen).resolve()
        runtime = self.state_dir.parent.resolve()
        external_paths(workspace, runtime, self.installed_root)
        from .ownership import bind_runtime, unbind_runtime
        from .store import FormStore
        from .state import _atomic_json
        config = workspace / "config"
        if (config.exists() and any(config.iterdir())) or (workspace / ".formfiller-owner.json").exists():
            raise WebError("existing_workspace_requires_migration", 409)
        if (runtime / ".formfiller-owner.json").exists() or (runtime / "browser-profile").exists():
            raise WebError("existing_runtime_requires_review", 409)
        if any(path.name != ".runner.lock" for path in self.state_dir.iterdir()):
            raise WebError("existing_runtime_requires_review", 409)
        config.mkdir(parents=True, exist_ok=True)
        owner, created = None, []
        try:
            for filename, value in (("forms.json", {"forms": []}), ("settings.json", {"live_enabled": False})):
                path = config / filename
                _atomic_json(path, value)
                created.append(path)
            owner = bind_runtime(workspace, runtime)
            locator = Path(os.environ["LOCALAPPDATA"]) / "FormFiller" / "paths.json"
            _atomic_json(locator, {"workspace": str(workspace), "runtime": str(runtime), "installed_app": str(self.installed_root)})
        except Exception:
            if owner:
                unbind_runtime(workspace, runtime, owner)
            for path in created:
                path.unlink()
            raise WebError("workspace_setup_failed") from None
        self.config_dir = config
        self.profile_dir = runtime / "browser-profile"
        self.store = FormStore(config)
        self.needs_setup = False
        return {"needs_setup": False}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, app):
        super().__init__(address, Handler)
        self.app = app


class Handler(BaseHTTPRequestHandler):
    server_version = "FormFiller"

    def log_message(self, *args):
        pass  # URLs, request bodies, and exception text never become diagnostics.

    def respond(self, status, value, content_type="application/json; charset=utf-8"):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8") if isinstance(value, (dict, list)) else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def guard(self, *, require_token=True):
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected_host:
            raise WebError("host_not_allowed", 403)
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{expected_host}":
            raise WebError("origin_not_allowed", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise WebError("origin_not_allowed", 403)
        if require_token and not secrets.compare_digest(self.headers.get("X-FormFiller-Token", ""), self.server.app.token):
            raise WebError("session_required", 403)

    def dispatch(self):
        path = urlsplit(self.path).path
        api = path.startswith("/api/")
        self.guard(require_token=api and path != "/api/session")
        app = self.server.app
        if self.command == "GET":
            routes = {"/api/session": lambda: {"csrf_token": app.token, "mode": app.mode, "needs_setup": app.needs_setup},
                      "/api/forms": lambda: {"forms": app.forms()}, "/api/today": app.status,
                      "/api/history": app.history, "/api/attendance": app.attendance, "/api/readiness": app.readiness,
                      "/api/sync": app.sync, "/api/skyward/config": app.skyward_settings}
            if path in routes:
                return self.respond(200, routes[path]())
            if path.startswith("/api/forms/"):
                return self.respond(200, app.form(unquote(path[len("/api/forms/"):])) )
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                     "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/static/styles.css": ("styles.css", "text/css; charset=utf-8")}
            if path not in files:
                raise WebError("not_found", 404)
            name, mime = files[path]
            return self.respond(200, (STATIC_ROOT / name).read_bytes(), mime)
        if self.command not in ("POST", "PUT", "DELETE"):
            raise WebError("method_not_allowed", 405)
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise WebError("request_invalid") from None
        if not 0 <= size <= 1024 * 1024:
            raise WebError("request_too_large", 413)
        if size and self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise WebError("json_required", 415)
        try:
            payload = json.loads(self.rfile.read(size)) if size else {}
        except (ValueError, UnicodeError):
            raise WebError("request_invalid") from None
        if not isinstance(payload, dict):
            raise WebError("request_invalid")
        if self.command == "POST" and path == "/api/forms/inspect":
            return self.respond(200, app.inspect(payload))
        if self.command == "POST" and path == "/api/workspace/choose":
            return self.respond(200, app.choose_workspace())
        if self.command == "POST" and path == "/api/forms":
            return self.respond(201, app.mutate_form(payload))
        if self.command == "POST" and path == "/api/attendance/load":
            return self.respond(200, app.load_roster(payload))
        if self.command == "POST" and path == "/api/attendance/marks":
            return self.respond(200, app.set_marks(payload))
        if self.command == "POST" and path == "/api/attendance/submit":
            return self.respond(200, app.submit_attendance())
        if self.command == "POST" and path == "/api/sign-in":
            return self.respond(200, app.start_sign_in(payload))
        if self.command == "PUT" and path == "/api/skyward/config":
            return self.respond(200, app.replace_skyward_config(payload))
        if self.command == "POST" and path == "/api/sync/check":
            return self.respond(200, app.sync())
        if self.command == "POST" and path == "/api/run":
            return self.respond(200, app.run_once())
        if self.command == "POST" and path.startswith("/api/forms/") and path.endswith("/approve"):
            form_id = unquote(path[len("/api/forms/"):-len("/approve")])
            return self.respond(200, app.approve_form(form_id, payload))
        if self.command == "POST" and path.startswith("/api/forms/") and path.endswith("/schedule"):
            form_id = unquote(path[len("/api/forms/"):-len("/schedule")])
            return self.respond(200, app.schedule_form(form_id, payload))
        if self.command == "POST" and path.startswith("/api/forms/") and path.endswith("/submit"):
            form_id = unquote(path[len("/api/forms/"):-len("/submit")])
            return self.respond(200, app.submit_form(form_id))
        if path.startswith("/api/forms/"):
            form_id = unquote(path[len("/api/forms/"):])
            if self.command == "PUT":
                return self.respond(200, app.mutate_form(payload, form_id))
            if self.command == "DELETE":
                with app.editing():
                    app.store.archive_form(form_id)
                app.sync_tasks()
                return self.respond(200, {"removed": True})
        raise WebError("not_found", 404)

    def handle_safely(self):
        try:
            self.dispatch()
        except WebError as exc:
            self.respond(exc.status, {"error": {"code": exc.code, "message": exc.code.replace("_", " ")}})
        except (BrowserError, StateError) as exc:
            code = str(exc.code).lower()
            code = code if SAFE_CODE.fullmatch(code) else "request_failed"
            self.respond(409, {"error": {"code": code, "message": code.replace("_", " ")}})
        except Exception:
            self.respond(400, {"error": {"code": "request_failed", "message": "request failed"}})

    do_GET = do_POST = do_PUT = do_DELETE = handle_safely


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", action="store_true", help="Use external private workspace with an installed snapshot.")
    parser.add_argument("--launch-installed", action="store_true", help="Launch the reviewed installed UI from this development checkout.")
    parser.add_argument("--open", action="store_true", help="Open the UI in the default browser.")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    temporary = None
    try:
        if args.launch_installed:
            from .workspace import resolve_workspace
            from .deployment import validate_snapshot
            installed = resolve_workspace().installed_app
            if installed is None:
                raise WebError("installed_snapshot_required")
            validate_snapshot(installed)
            launcher = installed / "Run-FormFillerPrivate.ps1"
            if not launcher.is_file():
                raise WebError("installed_snapshot_required")
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            command = ["pwsh", "-NoProfile", "-File", str(launcher)]
            if args.open:
                command += ["-WebArgs", "--open"]
            return subprocess.run(command, cwd=installed, env=environment).returncode
        if args.private:
            from .workspace import resolve_workspace
            installed = Path(__file__).resolve().parent.parent
            verify_installation(installed)
            paths = resolve_workspace(installed)
            config_dir = args.workspace / "config" if args.workspace else paths.config_dir
            state_dir = args.runtime / "state" if args.runtime else paths.state_dir
            profile_dir = args.runtime / "browser-profile" if args.runtime else paths.profile_dir
            needs_setup = config_dir.resolve().is_relative_to(installed)
            if needs_setup:
                runtime = Path(os.environ["LOCALAPPDATA"]) / "FormFiller" / "runtime"
                config_dir = runtime / "unconfigured"
                state_dir = runtime / "state"
                profile_dir = runtime / "browser-profile"
            if state_dir.resolve().is_relative_to(installed):
                raise WebError("external_workspace_required")
            if not needs_setup:
                external_paths(config_dir.parent, state_dir.parent, installed)
                if profile_dir.resolve() != (state_dir.parent / "browser-profile").resolve():
                    raise WebError("runtime_profile_invalid")
                if profile_dir.is_symlink() or profile_dir.is_junction():
                    raise WebError("workspace_link_not_allowed")
            app = WebApp(config_dir, state_dir, profile_dir, mode="private", installed_root=installed, needs_setup=needs_setup)
        else:
            temporary = tempfile.TemporaryDirectory(prefix="formfiller-demo-")
            root = Path(temporary.name)
            initialize_demo(root / "config", root / "state")
            app = WebApp(root / "config", root / "state", root / "browser-profile")
        server = Server(("127.0.0.1", args.port), app)
        print(f"FormFiller mode={app.mode} http://127.0.0.1:{server.server_port}", flush=True)
        if args.open:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{server.server_port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    except Exception as exc:
        code = getattr(exc, "code", "startup_failed")
        print("FormFiller code=" + (code if isinstance(code, str) and SAFE_CODE.fullmatch(code) else "startup_failed"), flush=True)
        return 2
    finally:
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
