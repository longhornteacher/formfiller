"""Windowless per-day dispatch through one-shot Windows tasks.

A planner task runs once each morning, assigns every scheduled template a random
time (see scheduling.py), deletes yesterday's plan and leftover tasks, and
registers one run-once task per distinct slot. Nothing runs between slots.
Tasks launch pythonw.exe, so no console window appears; output goes only to a
sanitized log in the designated local runtime. Task names carry times only,
never form aliases.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from . import scheduling
from .state import StateError, StateStore
from .workspace import WorkspaceError, resolve_workspace

ROOT = Path(__file__).resolve().parents[1]
PLANNER = "\\FormFiller\\Daily Plan"
RUN_PREFIX = "\\FormFiller\\Run "
LEGACY = "FormFiller Daily 3PM"
PLANNER_CENTRAL_MINUTE = 6 * 60
LOCK_WAIT_SECONDS = 20 * 60
LOCK_POLL_SECONDS = 15
LOG_LIMIT = 256 * 1024
_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"


class PlanError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _no_window_run(arguments, **options):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(arguments, capture_output=True, text=True, timeout=60,
                          creationflags=flags, check=False, **options)


def _user() -> str:
    domain, name = os.environ.get("USERDOMAIN"), os.environ.get("USERNAME")
    return f"{domain}\\{name}" if domain and name else (name or "")


def central_to_local(day, minute: int) -> datetime:
    """A Central wall-clock minute on `day`, as naive local time for Task Scheduler."""
    central = datetime(day.year, day.month, day.day, tzinfo=scheduling.ZONE) + timedelta(minutes=minute)
    return central.astimezone().replace(tzinfo=None, second=0, microsecond=0)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _settings(extra: str = "") -> str:
    return ("<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
            "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
            "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>"
            "<StartWhenAvailable>true</StartWhenAvailable><AllowStartOnDemand>true</AllowStartOnDemand>"
            "<Enabled>true</Enabled><Hidden>true</Hidden><WakeToRun>false</WakeToRun>"
            f"<ExecutionTimeLimit>PT30M</ExecutionTimeLimit>{extra}</Settings>")


def _task(description: str, triggers: str, settings: str, command: str, arguments: str, workdir: str) -> str:
    user = escape(_user())
    principal = (f"<Principals><Principal id=\"Author\"><UserId>{user}</UserId>"
                 "<LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>"
                 if user else "")
    return ('<?xml version="1.0" encoding="UTF-16"?>'
            f'<Task version="1.4" xmlns="{_NAMESPACE}">'
            f"<RegistrationInfo><Description>{escape(description)}</Description></RegistrationInfo>"
            f"<Triggers>{triggers}</Triggers>{principal}{settings}"
            f'<Actions Context="Author"><Exec><Command>{escape(command)}</Command>'
            f"<Arguments>{escape(arguments)}</Arguments><WorkingDirectory>{escape(workdir)}</WorkingDirectory>"
            "</Exec></Actions></Task>")


def windowless_python(python: str | Path) -> Path:
    candidate = Path(python).with_name("pythonw.exe")
    return candidate if candidate.is_file() else Path(python)


def run_task_xml(when: datetime, end: datetime, python, snapshot) -> str:
    trigger = (f"<TimeTrigger><StartBoundary>{_iso(when)}</StartBoundary>"
               f"<EndBoundary>{_iso(end)}</EndBoundary><Enabled>true</Enabled></TimeTrigger>")
    return _task("FormFiller: dispatch due templates once; no automatic retries.", trigger,
                 _settings("<DeleteExpiredTaskAfter>PT0S</DeleteExpiredTaskAfter>"),
                 str(windowless_python(python)), "-B -m formfiller.taskplan run", str(snapshot))


def planner_task_xml(day, python, snapshot) -> str:
    start = central_to_local(day, PLANNER_CENTRAL_MINUTE)
    user = escape(_user())
    triggers = (f"<CalendarTrigger><StartBoundary>{_iso(start)}</StartBoundary><Enabled>true</Enabled>"
                "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"
                f"<LogonTrigger><Enabled>true</Enabled><Delay>PT2M</Delay>"
                f"{f'<UserId>{user}</UserId>' if user else ''}</LogonTrigger>")
    return _task("FormFiller: plans today's randomized template times (12:00-15:30 Central). Submits nothing.",
                 triggers, _settings(), str(windowless_python(python)),
                 "-B -m formfiller.taskplan plan", str(snapshot))


class Scheduler:
    """Thin schtasks wrapper. `run` is injectable so tests never touch Windows."""

    def __init__(self, run=None):
        self._run = run or _no_window_run

    def run_tasks(self) -> list[str]:
        result = self._run(["schtasks.exe", "/Query", "/FO", "CSV", "/NH"])
        names = []
        for line in (result.stdout or "").splitlines():
            name = line.split('","')[0].strip('"')
            if name.lower().startswith(RUN_PREFIX.lower()):
                names.append(name)
        return names

    def create(self, name: str, xml: str) -> None:
        handle, path = tempfile.mkstemp(prefix="formfiller-task-", suffix=".xml")
        try:
            with os.fdopen(handle, "w", encoding="utf-16") as stream:
                stream.write(xml)
            result = self._run(["schtasks.exe", "/Create", "/TN", name, "/XML", path, "/F"])
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)
        if result.returncode != 0:
            raise PlanError("task_register_failed")

    def delete(self, name: str) -> None:
        self._run(["schtasks.exe", "/Delete", "/TN", name, "/F"])

    def clear_run_tasks(self) -> None:
        for name in self.run_tasks():
            self.delete(name)


def replace_run_tasks(scheduler, day, minutes, instant, python, snapshot) -> int:
    """Delete every run task, then register one per future slot and one catch-up."""
    scheduler.clear_run_tasks()
    now = instant.hour * 60 + instant.minute
    end = central_to_local(day, scheduling.END)
    when = {central_to_local(day, minute) for minute in minutes if minute > now}
    if any(minute <= now for minute in minutes):
        # Overdue slots run together as soon as possible, never after the window.
        when.add(instant.astimezone().replace(tzinfo=None, second=0, microsecond=0) + timedelta(minutes=1))
    created = 0
    for moment in sorted(when):
        if moment >= end:
            continue
        scheduler.create(f"{RUN_PREFIX}{moment:%H%M}", run_task_xml(moment, end, python, snapshot))
        created += 1
    return created


def sync_today(config_dir, state_dir, *, scheduler=None, python=None, snapshot=None, instant=None) -> dict:
    """Plan today (idempotently) and make the one-shot tasks match it.

    Returns sanitized status only. Raises StateError('lock_exists') when another
    FormFiller operation holds the shared lock; callers may retry.
    """
    from . import runner
    from .ownership import verify_runtime_owner
    scheduler = scheduler or Scheduler()
    python = python or sys.executable
    snapshot = Path(snapshot or ROOT)
    instant = instant or scheduling.now()
    config_dir, state_dir = Path(config_dir), Path(state_dir)
    today = instant.date()
    try:
        settings = runner._load_json(config_dir / "settings.json", "settings_config")
        forms = [form for form in runner._forms(config_dir / "forms.json") if scheduling.enabled(form)]
        if not isinstance(settings, dict) or settings.get("live_enabled", False) is not True:
            scheduler.clear_run_tasks()
            return {"code": "live_disabled", "tasks": 0}
        verify_runtime_owner(config_dir.parent, state_dir.parent)
        if not runner._load_calendar(settings, config_dir, today):
            scheduler.clear_run_tasks()
            scheduling.prune(StateStore(state_dir, today))
            return {"code": "not_school_day", "tasks": 0}
    except PlanError:
        raise
    except Exception as exc:  # fixed codes only; paths and answers never leave here
        code = getattr(exc, "code", None)
        if not isinstance(code, str) and isinstance(exc, ValueError):
            code = str(exc)
        scheduler.clear_run_tasks()
        return {"code": runner._safe_code(code, "plan_blocked"), "tasks": 0}
    store = StateStore(state_dir, today)
    with store.lock():
        data = scheduling.plan(store, forms, instant)
        scheduling.prune(store)
        minutes = scheduling.pending_minutes(store, forms, data)
    if instant.hour * 60 + instant.minute >= scheduling.END or not minutes:
        scheduler.clear_run_tasks()
        return {"code": "window_closed" if minutes else "nothing_due", "tasks": 0}
    return {"code": "planned", "tasks": replace_run_tasks(scheduler, today, minutes, instant, python, snapshot)}


def sync_for_ui(config_dir, state_dir, *, scheduler=None, attempts=5, pause=2.0, sleep=time.sleep):
    """Best-effort refresh after the WebUI changes a template's schedule.

    Only the designated installed snapshot may register tasks, so development
    checkouts and demos never touch Windows Task Scheduler.
    """
    try:
        workspace = resolve_workspace(ROOT)
        if workspace.installed_app is None or workspace.installed_app.resolve() != ROOT.resolve():
            return {"code": "not_installed_snapshot", "tasks": 0}
    except WorkspaceError:
        return {"code": "workspace_required", "tasks": 0}
    for attempt in range(attempts):
        try:
            return sync_today(config_dir, state_dir, scheduler=scheduler)
        except StateError as exc:
            if exc.code != "lock_exists" or attempt == attempts - 1:
                return {"code": exc.code, "tasks": 0}
            sleep(pause)
        except Exception:
            return {"code": "plan_failed", "tasks": 0}
    return {"code": "plan_failed", "tasks": 0}


def install_planner(*, scheduler=None, python=None, snapshot=None, instant=None) -> None:
    scheduler = scheduler or Scheduler()
    day = (instant or scheduling.now()).date()
    scheduler.create(PLANNER, planner_task_xml(day, python or sys.executable, Path(snapshot or ROOT)))
    scheduler.delete(LEGACY)


def uninstall(*, scheduler=None) -> None:
    scheduler = scheduler or Scheduler()
    scheduler.clear_run_tasks()
    scheduler.delete(PLANNER)


# --- windowless background entry points (pythonw: no console, no stdout) -----------

def _log_stream(state_dir: Path):
    path = state_dir / "background.log"
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_LIMIT:
            os.replace(path, path.with_suffix(".log.1"))
        return path.open("a", encoding="utf-8")
    return io.StringIO()


def run_with_lock_retry(run_once, *, sleep=time.sleep, clock=time.monotonic,
                        wait=LOCK_WAIT_SECONDS, poll=LOCK_POLL_SECONDS):
    """Retry only while the shared lock is busy. Nothing is claimed before the lock."""
    deadline = clock() + wait
    while True:
        code, text = run_once()
        if "code=lock_exists" not in text or clock() + poll >= deadline:
            return code, text
        sleep(poll)


def _run_once():
    from . import run_and_check
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        try:
            code = run_and_check.main(["--scheduled"])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
        except Exception:
            print("error code=background_failed")
            code = 2
    return int(code or 0), buffer.getvalue()


def main(argv=None) -> int:
    mode = (list(argv) if argv is not None else sys.argv[1:] or [""])[0]
    if mode not in ("plan", "run"):
        return 2
    sys.dont_write_bytecode = True
    try:
        workspace = resolve_workspace(ROOT)
    except WorkspaceError:
        return 0  # dormant until a human chooses the private workspace
    if workspace.installed_app is None:
        return 0
    stream = _log_stream(workspace.state_dir)
    stamp = scheduling.now().strftime("%Y-%m-%d %H:%M")
    try:
        if mode == "run":
            code, text = run_with_lock_retry(_run_once)
            lines = [line for line in text.splitlines() if line.strip()]
            for line in lines or ["run_exit=%d" % code]:
                stream.write(f"{stamp} run {line}\n")
            return code
        result = {"code": "plan_failed", "tasks": 0}
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                result = sync_today(workspace.config_dir, workspace.state_dir)
                break
            except StateError as exc:
                result = {"code": exc.code, "tasks": 0}
                if exc.code != "lock_exists" or time.monotonic() + LOCK_POLL_SECONDS >= deadline:
                    break
                time.sleep(LOCK_POLL_SECONDS)
            except Exception:
                break
        stream.write(f"{stamp} plan code={result['code']} tasks={result['tasks']}\n")
        return 0 if result["code"] in ("planned", "nothing_due", "window_closed", "not_school_day") else 2
    finally:
        stream.flush()
        if stream is not None and hasattr(stream, "close"):
            stream.close()


def _cli(argv) -> int:
    command = argv[0] if argv else ""
    if command in ("plan", "run"):
        return main([command])
    if command == "install-planner":
        install_planner()
        print("status=planner_installed")
        return 0
    if command == "uninstall":
        uninstall()
        print("status=tasks_removed")
        return 0
    print("usage: taskplan plan|run|install-planner|uninstall")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
