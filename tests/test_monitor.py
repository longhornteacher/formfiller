import argparse
import contextlib
import io
import json
import tempfile
import unittest
from datetime import date,time
from pathlib import Path
from unittest.mock import patch

from outputs.formfiller import monitor
from outputs.formfiller.calendar import CalendarError


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.today=date(2026,10,1)
        self.form_ids = [f"F{i:02d}" for i in range(1, 11)]
        self.forms = self.root/'forms.json'
        self.forms.write_text(json.dumps({"forms": [
            {"alias": x, "url": "https://forms.office.com/r?id=synthetic-" + x,
             "schema": {"questions": [{}]}, "answers": [{}]} for x in self.form_ids
        ]}))
        self.args=argparse.Namespace(calendar=self.root/'calendar.json',forms=self.forms,state_dir=self.root/'state',after=time(9),max_calendar_age_days=14,date_override=self.today)

    def tearDown(self):
        self.temp.cleanup()

    def run_monitor(self,calendar_result=True):
        with patch.object(monitor,'parse_args',return_value=self.args), patch.object(monitor,'load_calendar',return_value=calendar_result), contextlib.redirect_stdout(io.StringIO()):
            return monitor.main()

    def write_state(self,status):
        path=self.args.state_dir/self.today.isoformat()/'state.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(date=self.today.isoformat(),forms={a:dict(status=status) for a in self.form_ids})))

    def test_missing_due_run_is_incomplete(self):
        self.assertEqual(self.run_monitor(),1)

    def test_completed_run_without_forms_configuration(self):
        self.write_state('submitted')
        self.assertEqual(self.run_monitor(),0)

    def test_uncertain_run_is_incomplete(self):
        self.write_state('uncertain')
        self.assertEqual(self.run_monitor(),1)

    def test_non_school_day_needs_no_run_state(self):
        self.assertEqual(self.run_monitor(False),0)

    def test_invalid_calendar_is_error(self):
        with patch.object(monitor,'parse_args',return_value=self.args), patch.object(monitor,'load_calendar',side_effect=CalendarError('unapproved','private details')), contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(monitor.main(),2)
            self.assertNotIn('private details',output.getvalue())


if __name__=='__main__':
    unittest.main()
