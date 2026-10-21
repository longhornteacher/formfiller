"""Command-line orchestration for local Microsoft Forms preview/submission."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from . import scheduling
from .schema_changes import reconcile
from .state import _atomic_json
from .store import FormStore, template_fingerprint

try:  # Supports both `python -m formfiller.runner` and package import.
    from .state import StateError, StateStore
except ImportError:  # pragma: no cover - direct script fallback
    from state import StateError, StateStore

try:
    from .browser import BrowserError, BrowserSession
except ImportError:  # pragma: no cover - lets packaging provide browser later
    try:
        from browser import BrowserError, BrowserSession
    except ImportError:  # pragma: no cover
        BrowserError = RuntimeError  # type: ignore[misc,assignment]
        BrowserSession = None  # type: ignore[assignment,misc]

try:
    from .calendar import CalendarError, load_calendar
except ImportError:  # pragma: no cover
    try:
        from calendar import CalendarError, load_calendar  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        CalendarError = RuntimeError  # type: ignore[misc,assignment]
        load_calendar = None  # type: ignore[assignment,misc]

try:
    from .workspace import WorkspaceError, resolve_workspace
except ImportError:  # pragma: no cover
    from workspace import WorkspaceError, resolve_workspace

try:
    from .ownership import RuntimeOwnerError, verify_runtime_owner
except ImportError:  # pragma: no cover
    from ownership import RuntimeOwnerError, verify_runtime_owner


EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_NOT_SCHOOL_DAY = 3
EXIT_BROWSER = 4
EXIT_STATE = 5


class _GateError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path, code: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc


def _forms(path: Path) -> list[dict[str, Any]]:
    value = _load_json(path, "forms_config")
    forms = value.get("forms") if isinstance(value, dict) else value
    if not isinstance(forms, list):
        raise ValueError("forms_config")
    clean: list[dict[str, Any]] = []
    ids: set[str] = set()
    for form in forms:
        if not isinstance(form, dict):
            raise ValueError("forms_config")
        form_id = form.get("id", form.get("alias"))
        alias = form.get("alias", form_id)
        if (not isinstance(form_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", form_id)
                or form_id in ids or alias != form_id):
            raise ValueError("forms_config")
        ids.add(form_id)
        if form.get("active", True) is not True:
            continue
        schema = form.get("schema")
        answers = form.get("answers")
        questions = schema.get("questions") if isinstance(schema, dict) else None
        # A newly created web draft stays out of the run set until all three
        # setup fields are present. Its schema still needs explicit review.
        if (not isinstance(form.get("url"), str) or not form["url"] or schema is None
                or not isinstance(questions, list) or not questions
                or not isinstance(answers, list) or len(questions) != len(answers)):
            continue
        if not form["url"].startswith("https://"):
            raise ValueError("forms_config")
        normalized = dict(form)
        normalized["id"] = form_id
        normalized["alias"] = form_id
        normalized.setdefault("name", form_id)
        clean.append(normalized)
    return clean


def _today() -> date:
    return datetime.now(ZoneInfo("America/Chicago")).date()


def _migration_in_progress(root: Path) -> bool:
    return (root / ".migration.lock").exists()


def _config_fingerprint(form: dict[str, Any]) -> str:
    # The persisted value is a one-way digest; source material can include student details.
    return template_fingerprint(form)


def _remember_submission(config_dir, form, day, fingerprint):
    # Once submission is confirmed, a defaults-write failure must not cause an
    # uncertain outcome, a retry, or any repeat browser action.
    try:
        FormStore(config_dir).record_submission(form["alias"], form, day, fingerprint)
        return True
    except Exception:
        _emit(f"warning alias={form['alias']} code=last_submission_not_saved")
        return False


def _schema_fingerprint(schema: Any) -> str:
    return _canonical_hash(schema)


def _calendar_path(settings: dict[str, Any], config_dir: Path) -> Path:
    configured = settings.get("calendar_path", "calendar.json")
    path = Path(configured)
    return path if path.is_absolute() else (config_dir / path).resolve()


def _load_calendar(settings: dict[str, Any], config_dir: Path, today: date) -> bool:
    if load_calendar is None:
        raise ValueError("calendar_module")
    path = _calendar_path(settings, config_dir)
    return bool(load_calendar(path, today, max_age_days=int(settings.get("max_calendar_age_days", 14))))


def _safe_code(value: Any, default: str) -> str:
    code = value.lower() if isinstance(value, str) else default
    return code if code.replace("_", "").isalnum() and len(code) <= 48 else default


def _save_observed_schema(config_dir: Path, alias: str, schema: Any) -> None:
    destination = config_dir / "observed" / f"{alias}.schema.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".schema-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(schema, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _record_check(store: StateStore, alias: str, day: date, *, current: bool) -> None:
    """Remember when the live form was last compared; a match clears an old change notice."""
    _atomic_json(store.root / "checks" / f"{alias}.json", {"checked_on": day.isoformat()})
    if current:
        (store.root / "changes" / f"{alias}.json").unlink(missing_ok=True)


def _finish_live(store: StateStore, aliases: list[str]) -> dict[str, int]:
    counts = store.summary(aliases)
    _log_summary(store, counts)
    _emit(
        "summary date=" + store.day + " " + " ".join(f"{key}={counts[key]}" for key in
        ("submitted", "failed", "uncertain", "submitting", "pending", "missing"))
    )
    return counts


def _log_summary(store: StateStore, counts: dict[str, int]) -> None:
    try:
        store.log_summary(counts)
    except StateError as exc:
        _emit(f"warning code={exc.code}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview or submit configured school-day forms.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Submit after all safeguards pass.")
    mode.add_argument("--preview", action="store_true", help="Open the forms in visible preview mode.")
    mode.add_argument("--inspect", nargs="?", const="*", metavar="ALIAS", help="Capture schema(s) for onboarding; never submits.")
    mode.add_argument("--approve-schema", metavar="ALIAS", help="Approve the configured schema fingerprint for an alias.")
    mode.add_argument("--login", nargs="?", const="F01", metavar="ALIAS", help="Open the dedicated profile for manual sign-in; never submits.")
    parser.add_argument("--resume", action="store_true", help="Retry only pre-submit failures for this date.")
    parser.add_argument("--scheduled", action="store_true", help="Run only due scheduled templates, once, within the afternoon window.")
    parser.add_argument("--form", metavar="ALIAS", help="Run one saved form, whether or not it is scheduled.")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--state-dir", type=Path)
    return parser.parse_args(argv)


def _emit(message: str) -> None:
    # Messages are deliberately constrained to status codes and aliases.
    print(message, flush=True)


def _log(store: StateStore, alias: str | None, status: str, code: str | None = None) -> None:
    try:
        store.log(alias, status, code)
    except StateError as exc:
        suffix = f" alias={alias}" if alias is not None else ""
        _emit(f"warning code={exc.code}{suffix}")


def run(argv: Sequence[str] | None = None, *, project_root: Path | str | None = None) -> int:
    args = _parse_args(argv)
    if args.scheduled and (args.form or args.resume or args.preview or args.inspect is not None or args.login is not None or args.approve_schema):
        _emit("error code=schedule_mode_invalid")
        return EXIT_CONFIG
    root = Path(project_root or Path.cwd()).resolve()
    try:
        workspace = resolve_workspace(root)
    except WorkspaceError as exc:
        _emit(f"error code={exc.code}")
        return EXIT_CONFIG
    config_arg = args.config_dir or workspace.config_dir
    state_arg = args.state_dir or workspace.state_dir
    config_dir = config_arg if config_arg.is_absolute() else root / config_arg
    state_dir = state_arg if state_arg.is_absolute() else root / state_arg
    try:
        settings = _load_json(config_dir / "settings.json", "settings_config")
        forms = _forms(config_dir / "forms.json")
        if args.inspect is None and args.login is None and not args.approve_schema and not args.form:
            forms = [form for form in forms if scheduling.enabled(form)]
        if not isinstance(settings, dict):
            raise ValueError("settings_config")
        if type(settings.get("live_enabled", False)) is not bool:
            raise ValueError("settings_config")
        calendar_age = settings.get("max_calendar_age_days", 14)
        if type(calendar_age) is not int or calendar_age < 0:
            raise ValueError("settings_config")
        if not isinstance(settings.get("browser_profile_path", "browser-profile"), str):
            raise ValueError("settings_config")
        if not isinstance(settings.get("calendar_path", "calendar.json"), str):
            raise ValueError("settings_config")
    except ValueError as exc:
        _emit(f"error code={exc}")
        return EXIT_CONFIG

    try:
        today = _today()
        store = StateStore(state_dir, today)
    except Exception:
        _emit("error code=runner_clock_error")
        return EXIT_CONFIG
    if _migration_in_progress(root):
        _emit("error code=migration_in_progress")
        return EXIT_CONFIG
    if args.approve_schema:
        target = next((form for form in forms if form["alias"] == args.approve_schema), None)
        if target is None:
            _emit("error code=unknown_alias")
            return EXIT_CONFIG
        expected_fingerprint = _config_fingerprint(target)
        expected_schema = _schema_fingerprint(target["schema"])
        try:
            # Approval follows a fresh capture and binds schema + fixed answer policy.
            with store.lock():
                store.record_schema(target["alias"], expected_schema, approved=True, config_fingerprint=expected_fingerprint)
                _log(store, target["alias"], "schema_approved")
        except StateError as exc:
            _emit(f"error code={exc.code} alias={target['alias']}")
            return EXIT_STATE
        _emit(f"approved alias={target['alias']} fingerprint={expected_fingerprint[:12]}")
        return EXIT_OK

    inspect_alias = args.inspect
    login_alias = args.login
    if args.form and not any(form["alias"] == args.form for form in forms):
        _emit("error code=unknown_alias")
        return EXIT_CONFIG
    if login_alias and not any(form["alias"] == login_alias for form in forms):
        _emit("error code=unknown_alias")
        return EXIT_CONFIG
    if inspect_alias not in (None, "*") and not any(form["alias"] == inspect_alias for form in forms):
        _emit("error code=unknown_alias")
        return EXIT_CONFIG
    if inspect_alias is None and login_alias is None:
        try:
            school_day = _load_calendar(settings, config_dir, today)
        except (ValueError, CalendarError) as exc:
            code = _safe_code(getattr(exc, "code", None), "calendar_unavailable")
            _log(store, None, "calendar_error", code)
            _emit(f"error code={code}")
            return EXIT_CONFIG
        if not school_day:
            _log(store, None, "calendar_blocked", "not_school_day")
            _emit(f"skip code=not_school_day date={today.isoformat()}")
            return EXIT_NOT_SCHOOL_DAY

    if login_alias is not None:
        selected = [form for form in forms if form["alias"] == login_alias]
    else:
        selected = forms if inspect_alias in (None, "*") else [f for f in forms if f["alias"] == inspect_alias]
    if args.form:
        selected = [form for form in selected if form["alias"] == args.form]
    legacy_profile = workspace.profile_dir if workspace.external_workspace else (root / "config" / "browser-profile")
    profile = (str(workspace.profile_dir) if workspace.external_runtime else
               settings.get("browser_profile_path", str(legacy_profile)))
    profile_path = Path(profile)
    if not profile_path.is_absolute():
        profile_path = (root / profile_path).resolve()
    browser_config = dict(settings)
    browser_config["project_root"] = str(root)
    browser_config["browser_profile_path"] = str(profile_path)
    is_inspect = inspect_alias is not None
    is_login = login_alias is not None
    live = bool(args.live or args.scheduled or (not args.preview and not is_inspect and settings.get("live_enabled", False)))
    if is_inspect or is_login:
        live = False
    if live and not settings.get("live_enabled", False):
        _emit("error code=live_disabled")
        return EXIT_CONFIG
    if BrowserSession is None:
        _emit("error code=browser_module")
        return EXIT_CONFIG

    try:
        with store.lock():
            if _migration_in_progress(root):
                _emit("error code=migration_in_progress")
                return EXIT_CONFIG
            # The web editor and CLI share this lock. Reload private config after
            # acquiring it so a concurrent edit cannot leave a stale submission plan.
            settings = _load_json(config_dir / "settings.json", "settings_config")
            forms = _forms(config_dir / "forms.json")
            if args.inspect is None and args.login is None and not args.form:
                forms = [form for form in forms if scheduling.enabled(form)]
            if (not isinstance(settings, dict) or type(settings.get("live_enabled", False)) is not bool
                    or type(settings.get("max_calendar_age_days", 14)) is not int
                    or settings.get("max_calendar_age_days", 14) < 0):
                raise ValueError("settings_config")
            if login_alias and not any(form["alias"] == login_alias for form in forms):
                raise ValueError("unknown_alias")
            if inspect_alias not in (None, "*") and not any(form["alias"] == inspect_alias for form in forms):
                raise ValueError("unknown_alias")
            if login_alias is not None:
                selected = [form for form in forms if form["alias"] == login_alias]
            else:
                selected = forms if inspect_alias in (None, "*") else [f for f in forms if f["alias"] == inspect_alias]
            if args.form:
                selected = [form for form in selected if form["alias"] == args.form]
                if not selected:
                    raise ValueError("unknown_alias")
            legacy_profile = workspace.profile_dir if workspace.external_workspace else (root / "config" / "browser-profile")
            profile = (str(workspace.profile_dir) if workspace.external_runtime else
                       settings.get("browser_profile_path", str(legacy_profile)))
            profile_path = Path(profile)
            if not profile_path.is_absolute():
                profile_path = (root / profile_path).resolve()
            browser_config = dict(settings)
            browser_config["project_root"] = str(root)
            browser_config["browser_profile_path"] = str(profile_path)
            live = bool(args.live or args.scheduled or (not args.preview and not is_inspect and settings.get("live_enabled", False)))
            if is_inspect or is_login:
                live = False
            if live and not settings.get("live_enabled", False):
                raise ValueError("live_disabled")
            legacy_config = (root / "config").resolve()
            legacy_state = (root / "state").resolve()
            if live and (workspace.external_workspace or workspace.external_runtime
                         or config_dir.resolve() != legacy_config or state_dir.resolve() != legacy_state):
                verify_runtime_owner(config_dir.parent, state_dir.parent)
            if _migration_in_progress(root):
                _emit("error code=migration_in_progress")
                return EXIT_CONFIG
            if args.scheduled:
                # Settings may have changed while waiting for the shared lock.
                # Recheck the approved source before opening any Forms page.
                if not _load_calendar(settings, config_dir, today):
                    _emit(f"skip code=not_school_day date={today.isoformat()}")
                    return EXIT_NOT_SCHOOL_DAY
                instant = scheduling.now()
                if instant.date() != today:
                    raise ValueError("date_changed")
                selected = scheduling.due(store, forms, instant)
                if not selected:
                    return EXIT_OK
                # Durable claims prohibit retries after failures and interrupted starts.
                scheduling.claim(store, selected, instant)
            if not selected:
                return EXIT_OK
            session = BrowserSession(browser_config)
            with session:
                if is_login:
                    session.login(selected[0])
                    return EXIT_OK
                if is_inspect:
                    for form in selected:
                        observed = session.inspect(form)
                        fingerprint = _schema_fingerprint(observed)
                        _save_observed_schema(config_dir, form["alias"], observed)
                        store.record_schema(form["alias"], fingerprint, approved=False)
                        _log(store, form["alias"], "schema_captured", "approval_required")
                        _emit(f"captured alias={form['alias']} fingerprint={fingerprint[:12]} code=approval_required")
                    input("Schema capture is open in Edge. Press Enter to close the browser session. ")
                    return EXIT_OK

                if live:
                    # Preflight every schema and every alias state before the first click.
                    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
                    blocked = False
                    for form in selected:
                        alias = form["alias"]
                        fingerprint = _config_fingerprint(form)
                        record = store.bind_config(alias, fingerprint)
                        status = record["status"]
                        if status in {"submitted", "submitting", "uncertain"}:
                            _emit(f"skip alias={alias} code={status}")
                            _log(store, alias, "skipped", f"skip_{status}")
                            if status in {"submitting", "uncertain"}:
                                blocked = True
                            continue
                        if status == "failed" and not args.resume:
                            _emit(f"skip alias={alias} code=failed_use_resume")
                            _log(store, alias, "skipped", "failed_use_resume")
                            blocked = True
                            continue
                        if status == "pending" and args.resume:
                            _emit(f"skip alias={alias} code=not_failed")
                            _log(store, alias, "skipped", "not_failed")
                            blocked = True
                            continue
                        try:
                            observed = session.inspect(form)
                            observed_fp = _schema_fingerprint(observed)
                            expected_schema_fp = _schema_fingerprint(form["schema"])
                            if not store.schema_approved(alias, expected_schema_fp, fingerprint):
                                raise ValueError("schema_not_approved")
                            _record_check(store, alias, today, current=observed_fp == expected_schema_fp)
                            if observed_fp != expected_schema_fp:
                                _save_observed_schema(config_dir, alias, observed)
                                try:
                                    effective, changed = reconcile(form, observed, today)
                                except BrowserError:
                                    store.record_schema(alias, observed_fp, approved=False)
                                    _atomic_json(store.root / "changes" / f"{alias}.json", {"code": "schema_review_required"})
                                    raise ValueError("schema_mismatch") from None
                                if changed:
                                    _atomic_json(store.root / "changes" / f"{alias}.json", {"code": "schema_options_updated"})
                                    _emit(f"warning alias={alias} code=schema_options_updated")
                            else:
                                effective = form
                            session.preview(effective, today)
                            pending.append((effective, record))
                        except Exception as exc:
                            known = str(exc) if isinstance(exc, ValueError) and str(exc) in {"schema_mismatch", "schema_not_approved"} else None
                            code = _safe_code(getattr(exc, "code", known), "preflight_failed")
                            store.transition(alias, status, "failed", code)
                            _log(store, alias, "preflight_failed", code)
                            _emit(f"failed alias={alias} code={code}")
                            if args.scheduled:
                                blocked = True
                                continue
                            _finish_live(store, [form["alias"] for form in forms])
                            return EXIT_BROWSER if isinstance(exc, BrowserError) else EXIT_CONFIG
                    for form, record in pending:
                        alias = form["alias"]
                        prior = record["status"]
                        started = False

                        def before_submit(alias: str = alias, prior: str = prior) -> None:
                            nonlocal started
                            try:
                                current_day = _today()
                            except Exception:
                                _log(store, None, "calendar_error", "runner_clock_error")
                                raise _GateError("runner_clock_error") from None
                            if current_day != today:
                                _log(store, None, "calendar_blocked", "date_changed")
                                raise _GateError("date_changed")
                            if args.scheduled:
                                instant = scheduling.now()
                                if not scheduling.START <= instant.hour * 60 + instant.minute < scheduling.END:
                                    raise _GateError("schedule_window_closed")
                            try:
                                still_school_day = _load_calendar(settings, config_dir, today)
                            except (ValueError, CalendarError) as exc:
                                code = _safe_code(getattr(exc, "code", None), "calendar_unavailable")
                                _log(store, None, "calendar_error", code)
                                raise _GateError(code) from None
                            if not still_school_day:
                                _log(store, None, "calendar_blocked", "not_school_day")
                                raise _GateError("not_school_day")
                            store.transition(alias, prior, "submitting")
                            started = True
                            _log(store, alias, "submitting")

                        try:
                            session.submit(form, today, before_submit)
                            if started:
                                store.transition(alias, "submitting", "submitted")
                                _log(store, alias, "submitted")
                                submitted = True
                            else:
                                # Adapter returning without crossing the click boundary is a failure.
                                store.transition(alias, prior, "failed", "submit_not_started")
                                _log(store, alias, "failed", "submit_not_started")
                                _emit(f"failed alias={alias} code=submit_not_started")
                                blocked = True
                                submitted = False
                        except Exception as exc:
                            if started:
                                try:
                                    store.transition(alias, "submitting", "uncertain", "outcome_uncertain")
                                    _log(store, alias, "uncertain", "outcome_uncertain")
                                except StateError:
                                    pass
                                _emit(f"uncertain alias={alias} code=outcome_uncertain")
                                _finish_live(store, [item["alias"] for item in forms])
                            else:
                                code = _safe_code(getattr(exc, "code", str(exc)), "browser_error")
                                store.transition(alias, prior, "failed", code)
                                _log(store, alias, "failed", code)
                                _emit(f"failed alias={alias} code={code}")
                                _finish_live(store, [item["alias"] for item in forms])
                            return EXIT_BROWSER
                        if submitted:
                            _remember_submission(config_dir, form, today, record["config"])
                            _emit(f"submitted alias={alias} date={today.isoformat()}")
                        else:
                            _finish_live(store, [item["alias"] for item in forms])
                            return EXIT_BROWSER
                    counts = _finish_live(store, [form["alias"] for form in (selected if args.scheduled or args.form else forms)])
                    if counts["failed"] or counts["uncertain"] or counts["submitting"] or counts["pending"] or counts["missing"]:
                        blocked = True
                    return EXIT_BROWSER if blocked else EXIT_OK

                # Default preview keeps the browser visible until the operator closes it.
                for form in selected:
                    fingerprint = _config_fingerprint(form)
                    observed = session.inspect(form)
                    observed_fp = _schema_fingerprint(observed)
                    current = observed_fp == _schema_fingerprint(form["schema"])
                    _record_check(store, form["alias"], today, current=current)
                    if not current:
                        try:
                            reconcile(form, observed, today)
                            code = "schema_options_updated"
                        except BrowserError:
                            code = "schema_review_required"
                        _atomic_json(store.root / "changes" / f"{form['alias']}.json", {"code": code})
                        _emit(f"preview alias={form['alias']} code=schema_mismatch")
                        return EXIT_CONFIG
                    _emit(f"preview alias={form['alias']} date={today.isoformat()} schema={fingerprint[:12]}")
                    _log(store, form["alias"], "preview")
                    session.preview(form, today)
                input("Preview is open. Press Enter to close the browser session. ")
                return EXIT_OK
    except StateError as exc:
        _emit(f"error code={exc.code}")
        return EXIT_STATE
    except (ValueError, BrowserError) as exc:
        code = _safe_code(getattr(exc, "code", None), "runner_error")
        _emit(f"error code={code}")
        return EXIT_BROWSER if isinstance(exc, BrowserError) else EXIT_CONFIG
    except Exception:
        _emit("error code=runner_error")
        return EXIT_BROWSER


def main(argv: Sequence[str] | None = None) -> int:
    original_args = list(argv) if argv is not None else sys.argv[1:]
    module_root = Path(__file__).resolve().parents[1]
    if _migration_in_progress(module_root):
        _emit("error code=migration_in_progress")
        return EXIT_CONFIG
    try:
        workspace = resolve_workspace(module_root)
    except WorkspaceError as exc:
        _emit(f"error code={exc.code}")
        return EXIT_CONFIG
    external_paths = (workspace.external_workspace or workspace.external_runtime or
                      workspace.installed_app is not None or
                      any(arg in {"--config-dir", "--state-dir"} or arg.startswith(("--config-dir=", "--state-dir="))
                          for arg in original_args))
    if external_paths:
        installed = workspace.installed_app
        if installed is None:
            _emit("error code=installed_runner_required")
            return EXIT_CONFIG
        try:
            if installed.resolve() == module_root:
                from .deployment import DeploymentError, validate_snapshot
                validate_snapshot(installed, current_file=Path(__file__))
                sys.dont_write_bytecode = True
                return run(original_args, project_root=module_root)
            from .deployment import DeploymentError, validate_snapshot
            validate_snapshot(installed)
            interpreter = installed / ".venv" / "Scripts" / "python.exe"
            if not interpreter.is_file():
                interpreter = installed / ".venv" / "bin" / "python"
            if not interpreter.is_file():
                raise DeploymentError("installed_python_missing")
            child_env = os.environ.copy()
            child_env["FORM_FILLER_WORKSPACE"] = str(workspace.config_dir.parent)
            child_env["FORM_FILLER_RUNTIME"] = str(workspace.state_dir.parent)
            child_env["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [str(interpreter), "-m", "formfiller.runner", *original_args],
                cwd=installed, env=child_env, check=False,
            )
            return int(result.returncode)
        except DeploymentError as exc:
            _emit(f"error code={exc.code}")
            return EXIT_CONFIG
        except OSError:
            _emit("error code=installed_runner_unavailable")
            return EXIT_CONFIG
    return run(original_args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
