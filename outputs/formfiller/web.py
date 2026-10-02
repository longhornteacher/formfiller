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
from .runner import _config_fingerprint, _schema_fingerprint
from .state import StateError, StateStore

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
        if kind == "text" and isinstance(value, str):
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
        self.inspections = {}
        self.needs_setup = needs_setup

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

    def forms(self):
        if self.needs_setup:
            return []
        return [self.form(item["id"]) for item in self.store.list_forms()]

    def form(self, form_id):
        form = self.store.get_form(form_id)
        state = StateStore(self.state_dir, today())
        configured = bool(form.get("url") and form.get("schema") and form.get("answers"))
        approved = configured and state.schema_approved(form["alias"], _schema_fingerprint(form["schema"]), _config_fingerprint(form))
        return {"id": form["id"], "name": form["name"], "url": form.get("url", ""),
                "schema": normalized_schema(form.get("schema")), "answers": normalized_answers(form.get("answers")),
                "review_required": not approved, "configured": configured,
                "review_token": _config_fingerprint(form) if configured else None}

    def status(self):
        items = []
        state = StateStore(self.state_dir, today())
        for form in self.forms():
            record = state.read(form["id"]) or {}
            status = record.get("status", "pending")
            if status not in STATUSES:
                raise WebError("state_invalid")
            items.append({"id": form["id"], "name": form["name"], "status": status,
                          "review_required": form["review_required"]})
        counts = {status: sum(item["status"] == status for item in items) for status in STATUSES}
        checks = self.readiness()
        can_run = bool(items) and not any(item["review_required"] for item in items)
        can_run = can_run and not any(item["status"] in ("failed", "uncertain", "submitting") for item in items)
        can_run = can_run and not all(item["status"] == "submitted" for item in items)
        if self.mode == "private":
            can_run = can_run and checks["ready"]
        return {"date": today().isoformat(), "items": items, "counts": counts, "expected": len(items),
                "mode": self.mode, "can_run": can_run}

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
        forms = self.forms()
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
                "mode": self.mode}

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
        return {"schema": normalized_schema(schema), "inspect_token": token, "review_required": True}

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

    def run_once(self):
        if self.needs_setup:
            raise WebError("workspace_required", 409)
        if not self.operation.acquire(blocking=False):
            raise WebError("operation_in_progress", 409)
        try:
            if self.mode == "demo":
                with StateStore(self.state_dir, today()).lock():
                    for item in self.forms():
                        if item["review_required"]:
                            raise WebError("schema_review_required", 409)
                    state = StateStore(self.state_dir, today())
                    for item in self.forms():
                        record = state.bind_config(item["id"], _config_fingerprint(self.store.get_form(item["id"])))
                        if record["status"] == "submitted":
                            continue
                        if record["status"] != "pending":
                            raise WebError("manual_review_required", 409)
                        state.transition(item["id"], "pending", "submitting")
                        state.transition(item["id"], "submitting", "submitted")
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
                      "/api/history": app.history, "/api/readiness": app.readiness, "/api/sync": app.sync}
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
        if self.command == "POST" and path == "/api/sync/check":
            return self.respond(200, app.sync())
        if self.command == "POST" and path == "/api/run":
            return self.respond(200, app.run_once())
        if self.command == "POST" and path.startswith("/api/forms/") and path.endswith("/approve"):
            form_id = unquote(path[len("/api/forms/"):-len("/approve")])
            return self.respond(200, app.approve_form(form_id, payload))
        if path.startswith("/api/forms/"):
            form_id = unquote(path[len("/api/forms/"):])
            if self.command == "PUT":
                return self.respond(200, app.mutate_form(payload, form_id))
            if self.command == "DELETE":
                with app.editing():
                    app.store.archive_form(form_id)
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
        except Exception as exc:
            code = getattr(exc, "code", "request_failed")
            code = code if isinstance(code, str) and SAFE_CODE.fullmatch(code) else "request_failed"
            self.respond(400, {"error": {"code": code, "message": code.replace("_", " ")}})

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
                command += ["--open"]
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
