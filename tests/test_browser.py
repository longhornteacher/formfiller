"""Exercise the adapter with entirely fictional local HTML and no network."""
import copy
import builtins
import hashlib
import html
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from outputs.formfiller.browser import BrowserError, BrowserSession, answer_plan


TODAY = date(2026, 10, 1)
FORM = {
    "id": "F01",
    "alias": "F01",
    "name": "Synthetic fixture",
    "url": "https://forms.office.com/r?id=synthetic-fixture-001",
    "schema": {"questions": [
        {"title": "Fixture date", "required": True, "controls": [
            {"kind": "combobox", "label": "Date", "matrix": False, "placeholder": ""}]},
        {"title": "Fixture note", "required": True, "controls": [
            {"kind": "text", "label": "Note", "matrix": False, "placeholder": ""}]},
        {"title": "Fixture choice", "required": True, "controls": [
            {"kind": "radio", "label": "Yes", "matrix": False, "placeholder": ""},
            {"kind": "radio", "label": "No", "matrix": False, "placeholder": ""}]},
        {"title": "Fixture options", "required": True, "controls": [
            {"kind": "checkbox", "label": "Email", "matrix": False, "placeholder": ""},
            {"kind": "checkbox", "label": "Phone", "matrix": False, "placeholder": ""}]},
        {"title": "Fixture matrix", "required": False, "controls": [
            {"kind": "radio", "label": "Group A Given", "matrix": True, "placeholder": ""},
            {"kind": "radio", "label": "Group A Not given", "matrix": True, "placeholder": ""},
            {"kind": "radio", "label": "Group B Given", "matrix": True, "placeholder": ""},
            {"kind": "radio", "label": "Group B Not given", "matrix": True, "placeholder": ""}]},
    ]},
    "answers": [
        {"kind": "date"},
        {"kind": "text", "value": "Synthetic response"},
        {"kind": "radio", "values": ["Yes"]},
        {"kind": "checkbox", "values": ["Email", "Phone"]},
        {"kind": "matrix", "values": ["Group A Given"]},
    ],
}
FORMS = [FORM]


def fixture(form):
    blocks = []
    for i, question in enumerate(form['schema']['questions']):
        required = '<span data-automation-id="requiredStar"></span>' if question['required'] else ''
        controls = []
        for j, control in enumerate(question['controls']):
            label = html.escape(control['label'], quote=True)
            placeholder = html.escape(control['placeholder'], quote=True)
            kind = control['kind']
            if kind in ('radio', 'checkbox'):
                name = f'q{i}-row{j//2}' if control['matrix'] else f'q{i}'
                matrix = f'data-row-id="row{j//2}"' if control['matrix'] else ''
                controls.append(f'<label><input type="{kind}" role="{kind}" name="{name}" aria-label="{label}" {matrix}>{label}</label>')
            elif kind == 'textarea':
                controls.append(f'<textarea aria-label="{label}" placeholder="{placeholder}"></textarea>')
            else:
                role = 'role="combobox"' if kind == 'combobox' else ''
                type_attr = '' if kind == 'combobox' else 'type="text"'
                controls.append(f'<input {role} {type_attr} aria-label="{label}" placeholder="{placeholder}">')
        blocks.append(f'<div data-automation-id="questionItem"><span role="heading"><span class="text-format-content">{html.escape(question["title"])}</span>{required}</span>{"".join(controls)}</div>')
    title = html.escape(form.get('name', ''))
    return f'<html><head><title>{title} - Microsoft Forms</title></head><body><div data-automation-id="formTitle"><span class="text-format-content">{title}</span></div>'+''.join(blocks)+'''<button data-automation-id="submitButton" onclick="document.body.innerHTML='<p>Your response was submitted.</p>'">Submit</button></body></html>'''


class AnswerPlanTests(unittest.TestCase):
    def test_synthetic_schema_hash_is_stable(self):
        encoded = json.dumps(FORM['schema'], sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        self.assertEqual(hashlib.sha256(encoded.encode('utf-8')).hexdigest(),
                         'cc1f5066070ea5646fd1cc3a236e11f75545ee15c37676df5bdae6ca2d005d39')

    def test_all_answer_types_and_excluded_matrix_row(self):
        plan = answer_plan(FORM, TODAY)
        self.assertEqual(plan, [
            ['10/1/2026'], ['Synthetic response'], [True, False],
            [True, True], [True, False, False, False],
        ])

    def test_unknown_choice_and_required_matrix_exclusion_fail(self):
        form = copy.deepcopy(FORM)
        form['answers'][2]['values'].append('Invented option')
        with self.assertRaises(BrowserError) as caught:
            answer_plan(form, TODAY)
        self.assertEqual(caught.exception.code, 'ANSWER_CONFIG_INVALID')
        form = copy.deepcopy(FORM)
        form['schema']['questions'][4]['required'] = True
        with self.assertRaises(BrowserError) as caught:
            answer_plan(form, TODAY)
        self.assertEqual(caught.exception.code, 'REQUIRED_EXCLUDED_ROW')


class BrowserFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='formfiller-fixture-')
        self.session = BrowserSession({'browser_profile_path': str(Path(self.temp.name) / 'profile')})
        self.session.__enter__()
        self.external_requests = []
        urls = {form['url']: fixture(form) for form in FORMS}

        def route(request):
            if request.request.url in urls:
                request.fulfill(status=200, content_type='text/html', body=urls[request.request.url])
            else:
                self.external_requests.append(request.request.url)
                request.abort()
        self.session.context.route('**/*', route)

    def tearDown(self):
        self.session.__exit__()
        self.temp.cleanup()

    def test_synthetic_form_inspects_fills_and_reads_back(self):
        self.assertEqual(self.session.inspect(FORM), FORM['schema'])
        self.session.preview(FORM, TODAY)
        self.session.verify(FORM, TODAY)
        self.assertEqual(self.external_requests, [])

    def test_form_title_is_read_without_changing_the_schema(self):
        self.assertEqual(self.session.form_title(FORM), 'Synthetic fixture')
        self.assertEqual(self.session.inspect(FORM), FORM['schema'])
        self.session.pages[FORM['alias']].evaluate("() => document.querySelector('[data-automation-id=formTitle]').remove()")
        self.assertEqual(self.session.form_title(FORM), 'Synthetic fixture')  # falls back to the page title

    def test_local_browser_fixture_never_reads_private_forms_file(self):
        private_forms = (Path(__file__).resolve().parents[1] / 'outputs' / 'config' / 'forms.json').resolve()
        original_open = builtins.open
        original_path_open = Path.open

        def guarded_open(file, *args, **kwargs):
            if isinstance(file, (str, Path)) and Path(file).resolve() == private_forms:
                raise AssertionError('test attempted to read private forms configuration')
            return original_open(file, *args, **kwargs)

        def guarded_path_open(path, *args, **kwargs):
            if Path(path).resolve() == private_forms:
                raise AssertionError('test attempted to read private forms configuration')
            return original_path_open(path, *args, **kwargs)

        with patch('builtins.open', new=guarded_open), patch.object(Path, 'open', new=guarded_path_open):
            self.assertEqual(answer_plan(FORM, TODAY)[0], ['10/1/2026'])
            self.assertEqual(self.session.inspect(FORM), FORM['schema'])

    def test_matrix_excluded_row_stays_blank(self):
        self.session.preview(FORM, TODAY)
        controls = self.session.pages['F01'].locator('[data-automation-id="questionItem"]').nth(4).locator('input')
        self.assertTrue(controls.nth(0).is_checked())
        self.assertTrue(all(not controls.nth(i).is_checked() for i in (1, 2, 3)))

    def test_schema_change_blocks_before_click(self):
        form = copy.deepcopy(FORM)
        form['schema']['questions'][0]['required'] = False
        events = []
        with self.assertRaises(BrowserError) as caught:
            self.session.submit(form, TODAY, lambda: events.append('click-boundary'))
        self.assertEqual(caught.exception.code, 'FORM_FIELDS_CHANGED')
        self.assertEqual(events, [])

    def test_tampered_answer_blocks_before_click(self):
        self.session.preview(FORM, TODAY)
        page = self.session.pages['F01']
        page.locator('[data-automation-id="questionItem"]').nth(1).locator('input').fill('Changed')
        events = []
        with self.assertRaises(BrowserError) as caught:
            self.session.submit(FORM, TODAY, lambda: events.append('click-boundary'))
        self.assertEqual(caught.exception.code, 'ANSWER_VERIFICATION_FAILED')
        self.assertEqual(events, [])

    def test_mock_confirmation_after_durable_boundary(self):
        self.session.preview(FORM, TODAY)
        events = []
        self.session.submit(FORM, TODAY, lambda: events.append('durable-boundary'))
        self.assertEqual(events, ['durable-boundary'])
        self.assertEqual(self.external_requests, [])


if __name__ == '__main__':
    unittest.main()
