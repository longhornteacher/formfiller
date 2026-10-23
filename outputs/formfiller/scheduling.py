"""Daily randomized plans, stored only in the designated local runtime.

Call plan/claim while holding StateStore.lock. A claim is never automatically
retried, even if the process stops before opening Edge.
"""
from datetime import datetime
import random
from zoneinfo import ZoneInfo

from .state import StateError, _atomic_json

DEFAULT_ZONE = "America/Chicago"
DEFAULT_START = "12:00"
DEFAULT_END = "15:30"
ZONE = ZoneInfo(DEFAULT_ZONE)
ZONE_NAME = DEFAULT_ZONE
START = 12 * 60
END = 15 * 60 + 30


def _minutes(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":" or not (value[:2] + value[3:]).isdigit():
        raise ValueError("settings_window_invalid")
    hour, minute = int(value[:2]), int(value[3:])
    if hour > 23 or minute > 59:
        raise ValueError("settings_window_invalid")
    return hour * 60 + minute


def parse_window(settings):
    """Validate the submit window keys of settings.json; missing keys use the defaults.

    Returns (start_minute, end_minute, zone_name, ZoneInfo). Raises ValueError with
    a fixed code. Pure: it never changes the module's active window.
    """
    start = _minutes(settings.get("submit_window_start", DEFAULT_START))
    end = _minutes(settings.get("submit_window_end", DEFAULT_END))
    if start >= end:
        raise ValueError("settings_window_invalid")
    name = settings.get("time_zone", DEFAULT_ZONE)
    if not isinstance(name, str) or not name or name != name.strip() or name.startswith(("/", ".")) or ".." in name:
        raise ValueError("settings_time_zone_invalid")
    try:
        zone = ZoneInfo(name)
    except Exception:
        raise ValueError("settings_time_zone_invalid") from None
    return start, end, name, zone


def apply(settings):
    """Make a validated window the active one for this process."""
    global ZONE, ZONE_NAME, START, END
    START, END, ZONE_NAME, ZONE = parse_window(settings)


def apply_from_config(config_dir):
    """Best effort for entry points that only need the window: defaults on any problem."""
    import json
    from pathlib import Path
    try:
        settings = json.loads((Path(config_dir) / "settings.json").read_text(encoding="utf-8"))
        apply(settings if isinstance(settings, dict) else {})
    except (OSError, ValueError):
        apply({})


def _clock(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


def window_label():
    return f"{_clock(START)}–{_clock(END)} {ZONE_NAME}"


def now():
    return datetime.now(ZONE)


def enabled(form):
    # Existing templates stay scheduled when upgrading; new drafts opt in.
    return form.get("scheduled", True) is True


def plan(store, forms, instant):
    path = store.day_dir / "schedule.json"
    data = store._read_json(path, {"date": store.day, "slots": {}, "claimed": []})
    if (not isinstance(data, dict) or data.get("date") != store.day
            or not isinstance(data.get("slots"), dict) or not isinstance(data.get("claimed"), list)):
        raise StateError("schedule_invalid")
    slots = data["slots"]
    if (any(not isinstance(k, str) or type(v) is not int or not 0 <= v < 24 * 60 for k, v in slots.items())
            or any(not isinstance(alias, str) for alias in data["claimed"])):
        raise StateError("schedule_invalid")
    # A settings change can move the window mid-day: unclaimed slots outside it are re-planned.
    for alias in [k for k, v in slots.items() if not START <= v < END and k not in data["claimed"]]:
        del slots[alias]
    minute = instant.hour * 60 + instant.minute
    first = max(START, minute + (1 if minute >= START else 0))
    missing = [form["alias"] for form in forms if enabled(form) and form["alias"] not in slots]
    rng = random.SystemRandom()
    rng.shuffle(missing)
    available = [value for value in range(first, END) if value not in slots.values()]
    # Stratification spreads the templates across the remaining school afternoon.
    if missing and available:
        for index, alias in enumerate(missing):
            low = index * len(available) // len(missing)
            high = (index + 1) * len(available) // len(missing)
            slots[alias] = rng.choice(available[low:high] or available)
        _atomic_json(path, data)
    return data


def prune(store):
    """Delete every earlier day's timing; only today's plan is kept."""
    if not store.root.is_dir():
        return
    for directory in store.root.iterdir():
        if directory.is_dir() and directory.name != store.day and len(directory.name) == 10:
            (directory / "schedule.json").unlink(missing_ok=True)


def pending_minutes(store, forms, data):
    """Distinct slot minutes of scheduled templates that still need dispatch."""
    minutes = set()
    for form in forms:
        alias = form["alias"]
        record = store.read(alias)
        if (enabled(form) and alias not in data["claimed"] and alias in data["slots"]
                and (record is None or record.get("status") == "pending")):
            minutes.add(data["slots"][alias])
    return sorted(minutes)


def due(store, forms, instant):
    data = plan(store, forms, instant)
    minute = instant.hour * 60 + instant.minute
    if not START <= minute < END:
        return []
    candidates = []
    for form in forms:
        alias = form["alias"]
        record = store.read(alias)
        if (enabled(form) and alias not in data["claimed"]
                and data["slots"].get(alias, END) <= minute
                and (record is None or record.get("status") == "pending")):
            candidates.append(form)
    return sorted(candidates, key=lambda form: data["slots"][form["alias"]])


def claim(store, forms, instant):
    data = plan(store, forms, instant)
    data["claimed"].extend(form["alias"] for form in forms if form["alias"] not in data["claimed"])
    _atomic_json(store.day_dir / "schedule.json", data)
