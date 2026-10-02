"""Visible UI automation only. No private Forms endpoint is used."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse, parse_qs

QUESTION_SELECTOR = '[data-automation-id="questionItem"]'
SCHEMA_JS = r"""() => {
 const norm = s => (s||'').replace(/\s+/g,' ').trim();
 return {questions:Array.from(document.querySelectorAll('[data-automation-id="questionItem"]')).map(q=>({
 title:norm(q.querySelector('[role="heading"] .text-format-content')?.textContent),
 required:!!q.querySelector('[data-automation-id="requiredStar"]'),
 controls:Array.from(q.querySelectorAll('input,textarea,select')).map(e=>({
 kind:e.getAttribute('role')||e.getAttribute('type')||e.tagName.toLowerCase(),
 label:norm(e.getAttribute('aria-label')||Array.from((e.getAttribute('aria-labelledby')||'').split(' ')).map(id=>document.getElementById(id)?.textContent||'').join(' ')),
 matrix:!!e.getAttribute('data-row-id'),placeholder:e.getAttribute('placeholder')||''
 }))}))};
}"""


class BrowserError(Exception):
    def __init__(self, code: str, uncertain: bool = False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


def answer_plan(form: dict, today) -> list[list[object]]:
    """Produce a value for every observed control, including excluded rows."""
    try:
        return _answer_plan(form, today)
    except BrowserError:
        raise
    except (KeyError, TypeError, AttributeError, IndexError, ValueError):
        # Never surface malformed private configuration or Python exception text.
        raise BrowserError('ANSWER_CONFIG_INVALID') from None


def _answer_plan(form: dict, today) -> list[list[object]]:
    questions = form.get('schema', {}).get('questions', [])
    answers = form.get('answers', [])
    if not questions or len(questions) != len(answers):
        raise BrowserError('ANSWER_CONFIG_INVALID')
    result = []
    for question, answer in zip(questions, answers):
        controls = question['controls']
        kind = answer.get('kind')
        if kind == 'date':
            if len(controls) != 1 or controls[0]['kind'] != 'combobox':
                raise BrowserError('ANSWER_CONFIG_INVALID')
            result.append([f'{today.month}/{today.day}/{today.year}'])
        elif kind == 'text':
            if len(controls) != 1 or controls[0]['kind'] not in ('input', 'textarea', 'text'):
                raise BrowserError('ANSWER_CONFIG_INVALID')
            result.append([answer['value']])
        elif kind in ('radio', 'checkbox', 'matrix'):
            selected = answer.get('values', [])
            allowed_kind = 'checkbox' if kind == 'checkbox' else 'radio'
            available = [c['label'] for c in controls if c['kind'] == allowed_kind]
            if not selected or len(selected) != len(set(selected)) or not set(selected) <= set(available):
                raise BrowserError('ANSWER_CONFIG_INVALID')
            if kind == 'radio' and len(selected) != 1:
                raise BrowserError('ANSWER_CONFIG_INVALID')
            if kind == 'matrix':
                if not all(c['matrix'] for c in controls) or not all(s.endswith(' Given') for s in selected):
                    raise BrowserError('ANSWER_CONFIG_INVALID')
                # Required Likert matrices need every row; don't invent N/A answers.
                rows = {c['label'].rsplit(' ', 1)[0] for c in controls}
                if question['required'] and len(selected) != len(rows):
                    raise BrowserError('REQUIRED_EXCLUDED_ROW')
            result.append([c['label'] in selected if c['kind'] == allowed_kind else '' for c in controls])
        else:
            raise BrowserError('ANSWER_CONFIG_INVALID')
    return result


class BrowserSession:
    def __init__(self, config):
        self.config = config
        self.pages = {}
        self.context = None
        self.pw = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
            self.pw = sync_playwright().start()
            profile = Path(self.config.get('browser_profile_path', 'config/browser-profile')).resolve()
            # This directory is dedicated to this runner, never an everyday profile.
            self.context = self.pw.chromium.launch_persistent_context(
                str(profile), channel='msedge', headless=False,
                accept_downloads=False, locale='en-US', timezone_id='America/Chicago',
                viewport={'width': 1280, 'height': 900},
            )
            self.context.set_default_timeout(15000)
            return self
        except Exception:
            if self.pw:
                self.pw.stop()
            raise BrowserError('BROWSER_START_FAILED') from None

    def __exit__(self, *args):
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
        if self.pw:
            self.pw.stop()

    @staticmethod
    def _validate_url(url):
        value = urlparse(url)
        if (value.scheme != 'https' or value.hostname not in ('forms.cloud.microsoft', 'forms.office.com')
                or value.username or value.password or value.port not in (None, 443)
                or not parse_qs(value.query).get('id')):
            raise BrowserError('FORM_URL_INVALID')

    def _open(self, form):
        self._validate_url(form['url'])
        alias = form['alias']
        if alias not in self.pages:
            page = self.context.new_page()
            self.pages[alias] = page
            try:
                page.goto(form['url'], wait_until='domcontentloaded', timeout=45000)
                page.locator(QUESTION_SELECTOR).first.wait_for(state='visible', timeout=25000)
            except Exception:
                host = urlparse(page.url).hostname or ''
                if 'login' in host or 'signin' in host:
                    raise BrowserError('SIGN_IN_REQUIRED') from None
                raise BrowserError('FORM_UNAVAILABLE_OR_SIGN_IN_REQUIRED') from None
        page = self.pages[alias]
        actual = urlparse(page.url)
        if (actual.hostname not in ('forms.cloud.microsoft', 'forms.office.com') or
                parse_qs(actual.query).get('id') != parse_qs(urlparse(form['url']).query).get('id')):
            raise BrowserError('FORM_NAVIGATION_CHANGED')
        return page

    def inspect(self, form):
        try:
            schema = self._open(form).evaluate(SCHEMA_JS)
            if not schema['questions'] or any(not q['title'] or not q['controls'] for q in schema['questions']):
                raise BrowserError('FORM_SCHEMA_UNSUPPORTED')
            return schema
        except BrowserError:
            raise
        except Exception:
            raise BrowserError('FORM_INSPECTION_FAILED') from None

    def _validate_schema(self, form):
        if self.inspect(form) != form.get('schema'):
            raise BrowserError('FORM_FIELDS_CHANGED')

    def preview(self, form, today):
        self._validate_schema(form)
        page = self._open(form)
        plan = answer_plan(form, today)
        try:
            questions = page.locator(QUESTION_SELECTOR)
            for i, expected in enumerate(plan):
                controls = questions.nth(i).locator('input,textarea,select')
                # Nonselected radios cannot be unchecked through accessible UI;
                # fresh pages and readback enforce blank excluded matrix rows.
                for j, value in enumerate(expected):
                    control = controls.nth(j)
                    if isinstance(value, bool):
                        if value:
                            control.check()
                        elif form['schema']['questions'][i]['controls'][j]['kind'] == 'checkbox':
                            control.uncheck()
                    elif control.input_value() != value:
                        # Focusing an unused Other field can select its radio.
                        if form['schema']['questions'][i]['controls'][j]['placeholder'] == 'Other':
                            raise BrowserError('ANSWER_VERIFICATION_FAILED')
                        control.fill(value)
                        control.press('Tab')
            self.verify(form, today)
        except BrowserError:
            raise
        except Exception:
            raise BrowserError('FORM_FILL_FAILED') from None

    def verify(self, form, today):
        self._validate_schema(form)
        page = self._open(form)
        expected = answer_plan(form, today)
        actual = page.evaluate(r"""() => Array.from(document.querySelectorAll('[data-automation-id="questionItem"]')).map(q=>Array.from(q.querySelectorAll('input,textarea,select')).map(e=>e.matches('[type="radio"],[type="checkbox"]') ? e.checked : e.value))""")
        if actual != expected:
            raise BrowserError('ANSWER_VERIFICATION_FAILED')
        if page.locator('[aria-invalid="true"]').count():
            raise BrowserError('FORM_VALIDATION_FAILED')

    def submit(self, form, today, before_submit_callback):
        self.verify(form, today)
        page = self._open(form)
        button = page.locator('[data-automation-id="submitButton"]')
        if button.count() != 1 or not button.is_enabled() or not button.is_visible():
            raise BrowserError('SUBMIT_CONTROL_CHANGED')
        before_submit_callback()
        try:
            button.click(timeout=15000)
            confirmation = page.get_by_text('Your response was submitted.', exact=True)
            confirmation.wait_for(state='visible', timeout=30000)
            if page.locator(QUESTION_SELECTOR).count() or button.is_visible():
                raise BrowserError('SUBMISSION_UNCONFIRMED', uncertain=True)
        except Exception:
            # A timeout can happen after the server received a response.
            raise BrowserError('SUBMISSION_UNCONFIRMED', uncertain=True) from None

    def login(self, form):
        self._validate_url(form['url'])
        page = self.context.new_page()
        try:
            page.goto(form['url'], wait_until='domcontentloaded', timeout=45000)
            input('Sign into the district account in Edge, then press Enter here. No responses will be submitted. ')
        except Exception:
            raise BrowserError('SIGN_IN_NOT_COMPLETED') from None
