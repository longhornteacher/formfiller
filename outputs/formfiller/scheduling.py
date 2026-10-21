"""Daily randomized plans, stored only in the designated local runtime.

Call plan/claim while holding StateStore.lock. A claim is never automatically
retried, even if the process stops before opening Edge.
"""
from datetime import datetime
import random
from zoneinfo import ZoneInfo

from .state import StateError, _atomic_json

ZONE = ZoneInfo("America/Chicago")
START = 12 * 60
END = 15 * 60 + 30


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
    if (any(not isinstance(k, str) or type(v) is not int or not START <= v < END for k, v in slots.items())
            or any(not isinstance(alias, str) for alias in data["claimed"])):
        raise StateError("schedule_invalid")
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
