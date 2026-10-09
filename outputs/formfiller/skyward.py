"""Skyward attendance: read a class-roster table and stage attendance marks.

Student names are sensitive. They live only in memory (WebApp) and are never written
to state, logs, reports, or error codes. Persisted records hold counts only.
"""
from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from .browser import BrowserError, BrowserSession

MARKS = ("present", "absent", "tardy")
NAME_HEADERS = ("student", "student name", "name")
# The roster is the innermost table that has both the Absent and Present columns.
ROSTER_TABLE_JS = r"""() => {
 const tables = Array.from(document.querySelectorAll('table')).filter(t =>
   /Absent/.test(t.innerText) && /Present/.test(t.innerText) && !t.querySelector('table'));
 return tables.length ? tables[0].outerHTML : null;
}"""


class _TableParser(HTMLParser):
    """Collect rows of cell text from the first <table> in a document."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self._row, self._cell = [], None, None
        self._depth = 0
        self._done = False

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        if tag == "table":
            self._depth += 1
        elif self._depth == 1 and tag == "tr":
            self._row = []
        elif self._depth == 1 and tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if self._done:
            return
        if tag == "table":
            self._depth -= 1
            if self._depth == 0:
                self._done = True
        elif self._depth == 1 and tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif self._depth == 1 and tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None and not self._done:
            self._cell.append(data)


def parse_roster_table(html: str) -> list[dict]:
    """Return [{"name", "details"}] from a roster table with a header row.

    The student column is the first header named like "Student"/"Name"; every other
    column is kept as read-only detail text (e.g. Period, Grade).
    """
    if not isinstance(html, str) or not html.strip():
        raise BrowserError("ROSTER_TABLE_EMPTY")
    parser = _TableParser()
    parser.feed(html)
    if len(parser.rows) < 2:
        raise BrowserError("ROSTER_TABLE_EMPTY")
    header = [cell.lower() for cell in parser.rows[0]]
    name_index = next((header.index(h) for h in NAME_HEADERS if h in header), None)
    if name_index is None:
        raise BrowserError("ROSTER_NAME_COLUMN_MISSING")
    roster = []
    for row in parser.rows[1:]:
        if len(row) <= name_index or not row[name_index]:
            continue
        details = {parser.rows[0][i]: value for i, value in enumerate(row)
                   if i != name_index and i < len(parser.rows[0]) and value}
        roster.append({"name": row[name_index], "details": details})
    if not roster:
        raise BrowserError("ROSTER_TABLE_EMPTY")
    return roster


def validate_skyward_url(url: str, allowed_host: str) -> None:
    value = urlparse(url if isinstance(url, str) else "")
    if (value.scheme != "https" or not allowed_host or value.hostname != allowed_host.lower()
            or value.username or value.password or value.port not in (None, 443)):
        raise BrowserError("SKYWARD_URL_INVALID")


def load_config(raw) -> dict:
    """Validate private config/skyward.json: {"login_url": "...", "courses": [{"id","name","period"}]}."""
    if not isinstance(raw, dict) or not isinstance(raw.get("login_url"), str):
        raise BrowserError("SKYWARD_CONFIG_INVALID")
    host = urlparse(raw["login_url"]).hostname or ""
    validate_skyward_url(raw["login_url"], host)
    courses = raw.get("courses")
    if not isinstance(courses, list) or not courses:
        raise BrowserError("SKYWARD_CONFIG_INVALID")
    seen = set()
    for course in courses:
        if (not isinstance(course, dict) or not re.fullmatch(r"\d{3,12}", str(course.get("id", "")))
                or not isinstance(course.get("name"), str) or not course["name"].strip()
                or str(course["id"]) in seen):
            raise BrowserError("SKYWARD_CONFIG_INVALID")
        seen.add(str(course["id"]))
    return {"login_url": raw["login_url"], "host": host,
            "courses": [{"id": str(c["id"]), "name": c["name"].strip(), "period": str(c.get("period", "")).strip()}
                        for c in courses]}


# --- The "J" rule -----------------------------------------------------------------
# A cell such as "J -" or "E - M" lists the codes in the periods next to this one.
# Only "J" matters: a J on either side marks the student absent.

def code_is_absent(cell: str) -> bool:
    return any(token.upper() == "J" for token in re.split(r"[\s\-]+", cell or "") if token)


def today_header(headers: list[str], day) -> str | None:
    """The date column for `day`, e.g. a header containing "10/09". Past days are never used."""
    label = f"{day.month:02}/{day.day:02}"
    matches = [h for h in headers if label in re.sub(r"\s+", " ", h)]
    return matches[0] if len(matches) == 1 else None


def suggest_mark(details: dict, day) -> str:
    header = today_header(list(details), day)
    return "absent" if header and code_is_absent(details[header]) else "present"


def demo_courses() -> list[dict]:
    return [{"id": "1000001", "name": "Example Athletics", "period": "1st"},
            {"id": "1000002", "name": "Example ELA", "period": "6th and 7th"}]


def demo_roster(day) -> list[dict]:
    """Fictional students. Yesterday's J (Casey) must not count; today's J (Avery, Finley) must."""
    today_col, past_col = f"{day:%a} {day.month:02}/{day.day:02}", "Thu 01/01"
    rows = [("Avery Birchwood", "J -", ""), ("Blair Cobblestone", "", ""), ("Casey Dandelion", "", "J -"),
            ("Devon Elderberry", "E - M", ""), ("Emery Fernhollow", "", ""), ("Finley Goldenrod", "- J", ""),
            ("Harper Hazelnut", "", ""), ("Jordan Juniper", "", "")]
    return [{"name": name, "details": {"Gr": "08", today_col: now, past_col: before}} for name, now, before in rows]


class SkywardSession(BrowserSession):
    """Reads Skyward through the dedicated, manually signed-in Edge profile.

    Navigation: login URL -> Teacher Access -> Post Daily Attendance -> course "By Name".
    UNVERIFIED against the live page until a real attendance day; failures return codes only.
    """

    @staticmethod
    def _frames(page):
        return [page, *page.frames]

    def _click_text(self, page, text, timeout=20000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            for frame in self._frames(page):
                link = frame.get_by_text(text, exact=True)
                if link.count():
                    link.first.click()
                    return
            page.wait_for_timeout(300)
        raise BrowserError("SKYWARD_NAVIGATION_FAILED")

    def open_course(self, config: dict, course_id: str):
        course = next((c for c in config["courses"] if c["id"] == course_id), None)
        if not course:
            raise BrowserError("SKYWARD_COURSE_UNKNOWN")
        validate_skyward_url(config["login_url"], config["host"])
        page = self.context.new_page()
        try:
            page.goto(config["login_url"], wait_until="domcontentloaded", timeout=45000)
            try:
                self._click_text(page, "Teacher Access")
            except BrowserError:
                raise BrowserError("SIGN_IN_REQUIRED") from None
            if urlparse(page.url).hostname != config["host"].lower():
                raise BrowserError("SKYWARD_NAVIGATION_CHANGED")
            self._click_text(page, "Post Daily Attendance")
            deadline = time.monotonic() + 20
            link = None
            while link is None and time.monotonic() < deadline:
                for frame in self._frames(page):
                    candidate = frame.locator(f'a[href*="submitSelected(\\"{course["id"]},"]')
                    if candidate.count():
                        link = candidate.first
                        break
                else:
                    page.wait_for_timeout(300)
            if link is None:
                raise BrowserError("SKYWARD_COURSE_NOT_FOUND")
            link.click()
            return page
        except BrowserError:
            page.close()
            raise
        except Exception:
            page.close()
            raise BrowserError("SKYWARD_NAVIGATION_FAILED") from None

    def read_roster(self, config: dict, course_id: str) -> list[dict]:
        page = self.open_course(config, course_id)
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                for frame in self._frames(page):
                    html = frame.evaluate(ROSTER_TABLE_JS)
                    if html:
                        if urlparse(page.url).hostname != config["host"].lower():
                            raise BrowserError("SKYWARD_NAVIGATION_CHANGED")
                        return parse_roster_table(html)
                page.wait_for_timeout(400)
            raise BrowserError("ROSTER_UNAVAILABLE")
        finally:
            page.close()


def staged_counts(roster: list[dict], marks: dict) -> dict:
    counts = {mark: 0 for mark in MARKS}
    for student in roster:
        counts[marks.get(student["id"], "present")] += 1
    return counts
