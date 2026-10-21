import http.client
import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path

from outputs.formfiller import skyward, web
from outputs.formfiller.browser import BrowserError

TABLE = """<table><tr><th>Student</th><th>Period</th><th>Grade</th></tr>
<tr><td> Avery  Birchwood </td><td>1</td><td>6</td></tr>
<tr><td>Blair Cobblestone</td><td>1</td><td></td></tr>
<tr><td></td><td>1</td><td>6</td></tr></table>
<table><tr><td>ignored</td></tr></table>"""


class ParseRosterTests(unittest.TestCase):
    def test_reads_names_and_details(self):
        roster = skyward.parse_roster_table(TABLE)
        self.assertEqual([s["name"] for s in roster], ["Avery Birchwood", "Blair Cobblestone"])
        self.assertEqual(roster[0]["details"], {"Period": "1", "Grade": "6"})
        self.assertEqual(roster[1]["details"], {"Period": "1"})

    def test_rejects_missing_name_column_and_empty_tables(self):
        with self.assertRaises(BrowserError) as raised:
            skyward.parse_roster_table("<table><tr><th>Seat</th></tr><tr><td>1</td></tr></table>")
        self.assertEqual(raised.exception.code, "ROSTER_NAME_COLUMN_MISSING")
        for html in ("", None, "<p>none</p>", "<table><tr><th>Student</th></tr></table>"):
            with self.assertRaises(BrowserError):
                skyward.parse_roster_table(html)

    def test_url_must_match_configured_https_host(self):
        skyward.validate_skyward_url("https://skyward.example.org/home", "skyward.example.org")
        for url in ("http://skyward.example.org/", "https://evil.example.com/", "https://user:pw" + "@skyward.example.org/",
                    "https://skyward.example.org:8443/", None):
            with self.assertRaises(BrowserError):
                skyward.validate_skyward_url(url, "skyward.example.org")
        with self.assertRaises(BrowserError):
            skyward.validate_skyward_url("https://skyward.example.org/", "")


class RuleAndConfigTests(unittest.TestCase):
    def test_j_on_either_side_means_absent(self):
        for cell in ("J -", "- J", "J - J", "j -", "J"):
            self.assertTrue(skyward.code_is_absent(cell), cell)
        for cell in ("", "E - M", "E - X", "- N", "JJ", None):
            self.assertFalse(skyward.code_is_absent(cell), cell)

    def test_only_todays_column_counts(self):
        day = date(2026, 10, 13)
        self.assertEqual(skyward.today_header(["Gr", "Tue 10/13", "Mon 10/12"], day), "Tue 10/13")
        self.assertIsNone(skyward.today_header(["Mon 10/12", "Sun 10/11"], day))
        self.assertIsNone(skyward.today_header(["Tue 10/13", "Tue 10/13"], day))
        details = {"Tue 10/13": "E - M", "Mon 10/12": "J -"}
        self.assertEqual(skyward.suggest_mark(details, day), "present")
        details["Tue 10/13"] = "- J"
        self.assertEqual(skyward.suggest_mark(details, day), "absent")
        self.assertEqual(skyward.suggest_mark({"Mon 10/12": "J -"}, day), "present")

    def test_config_validation(self):
        good = {"login_url": "https://skyward.example.org/login", "courses": [{"id": "123456", "name": " PE ", "period": "1st"}]}
        config = skyward.load_config(good)
        self.assertEqual((config["host"], config["courses"][0]["name"]), ("skyward.example.org", "PE"))
        for bad in (None, {}, {**good, "login_url": "http://skyward.example.org/"}, {**good, "courses": []},
                    {**good, "courses": [{"id": "abc", "name": "x"}]},
                    {**good, "courses": [{"id": "123456", "name": "a"}, {"id": "123456", "name": "b"}]}):
            with self.assertRaises(BrowserError):
                skyward.load_config(bad)


class AttendanceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        web.initialize_demo(root / "config", root / "state")
        self.app = web.WebApp(root / "config", root / "state", root / "profile")
        self.server = web.Server(("127.0.0.1", 0), self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def call(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request(method, path, body=json.dumps(body) if body is not None else None,
                           headers={"Content-Type": "application/json", "X-FormFiller-Token": self.app.token})
        response = connection.getresponse()
        data = json.loads(response.read())
        connection.close()
        return response.status, data

    def test_demo_flow_marks_and_submits_once(self):
        status, data = self.call("GET", "/api/attendance")
        self.assertEqual((status, data["loaded"]), (200, False))
        self.assertEqual(self.call("POST", "/api/attendance/load", {})[1]["error"]["code"], "course_required")
        self.assertEqual(self.call("POST", "/api/attendance/load", {"course": "9"})[1]["error"]["code"], "skyward_course_unknown")
        status, data = self.call("POST", "/api/attendance/load", {"course": "1000001"})
        self.assertEqual(status, 200)
        students = data["students"]
        # Only today's J codes pre-mark absences (Avery, Finley); yesterday's J (Casey) is ignored.
        self.assertEqual([s["name"].split()[0] for s in students if s["mark"] == "absent"], ["Avery", "Finley"])
        self.assertEqual(data["counts"], {"present": len(students) - 2, "absent": 2, "tardy": 0})
        status, data = self.call("POST", "/api/attendance/marks",
                                 {"marks": {students[0]["id"]: "absent", students[1]["id"]: "tardy"}})
        self.assertEqual((status, data["counts"]["absent"], data["counts"]["tardy"]), (200, 1, 1))
        status, data = self.call("POST", "/api/attendance/submit")
        self.assertEqual((status, data["submitted"]), (200, True))
        self.assertEqual(self.call("POST", "/api/attendance/submit")[1]["error"]["code"], "attendance_already_submitted")
        self.assertEqual(self.call("POST", "/api/attendance/marks", {"marks": {}})[0], 409)
        self.assertEqual(self.call("POST", "/api/attendance/load", {"course": "1000001"})[0], 409)

    def test_invalid_marks_and_early_submit_are_rejected(self):
        self.assertEqual(self.call("POST", "/api/attendance/submit")[1]["error"]["code"], "roster_required")
        self.call("POST", "/api/attendance/load", {"course": "1000001"})
        for marks in ({"s0": "vacation"}, {"nobody": "absent"}, ["s0"]):
            self.assertEqual(self.call("POST", "/api/attendance/marks", {"marks": marks})[1]["error"]["code"], "marks_invalid")

    def test_names_are_never_persisted(self):
        self.call("POST", "/api/attendance/load", {"course": "1000001"})
        self.call("POST", "/api/attendance/submit")
        for path in Path(self.temp.name).rglob("*"):
            if path.is_file():
                self.assertNotIn("Birchwood", path.read_text(encoding="utf-8", errors="ignore"))


if __name__ == "__main__":
    unittest.main()
