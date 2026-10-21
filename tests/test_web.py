import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from outputs.formfiller import web


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        web.initialize_demo(self.root / 'config', self.root / 'state')
        self.app = web.WebApp(self.root / 'config', self.root / 'state', self.root / 'profile')
        self.server = web.Server(('127.0.0.1', 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, *, token=True, extra=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-FormFiller-Token'] = self.app.token
        headers.update(extra or {})
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        value = json.loads(raw) if response.getheader('Content-Type', '').startswith('application/json') else raw
        result = response.status, value, dict(response.getheaders())
        connection.close()
        return result

    def test_private_reads_and_mutations_require_session(self):
        self.assertEqual(self.request('GET', '/api/session', token=False)[0], 200)
        self.assertEqual(self.request('GET', '/api/forms', token=False)[0], 403)
        self.assertEqual(self.request('POST', '/api/forms', {'name': 'Example'}, token=False)[0], 403)

    def test_origin_and_host_rejected(self):
        self.assertEqual(self.request('GET', '/api/session', extra={'Origin': 'https://example.invalid'})[0], 403)
        self.assertEqual(self.request('GET', '/api/session', extra={'Host': 'example.invalid'})[0], 403)
        self.assertEqual(self.request('GET', '/api/session', extra={'Sec-Fetch-Site': 'cross-site'})[0], 403)

    def test_normalized_answers_preserve_original_plan(self):
        _, data, _ = self.request('GET', '/api/forms')
        form = data['forms'][0]
        self.assertEqual(form['answers']['q1'], 'Option A')
        self.assertEqual(form['schema']['questions'][2]['type'], 'date')
        original = self.app.store.get_form(form['id'])
        restored = web.runner_answers(original['schema'], form['answers'])
        self.assertEqual(restored, original['answers'])

    def test_edit_invalidates_review_but_rename_does_not(self):
        original = self.app.form('F01')
        _, renamed, _ = self.request('PUT', '/api/forms/F01', {'name': 'Renamed example'})
        self.assertFalse(renamed['review_required'])
        answers = dict(original['answers'], q0='Changed synthetic answer')
        _, changed, _ = self.request('PUT', '/api/forms/F01', {'answers': answers})
        self.assertTrue(changed['review_required'])
        self.assertEqual(changed['id'], 'F01')
        self.assertFalse(self.app.status()['can_run'])

    def test_inspect_create_archive_preserves_history_and_identity(self):
        url = 'https://forms.office.com/Pages/ResponsePage.aspx?id=synthetic-added'
        with patch.object(web.BrowserSession, '__enter__', side_effect=AssertionError('demo opened browser')):
            code, inspected, _ = self.request('POST', '/api/forms/inspect', {'url': url})
        self.assertEqual(code, 200)
        payload = {'name': 'Added example', 'url': url, 'inspect_token': inspected['inspect_token'],
                   'answers': {'q0': 'Example', 'q1': 'Option A'}}
        code, created, _ = self.request('POST', '/api/forms', payload)
        self.assertEqual(code, 201)
        self.assertTrue(created['review_required'])
        code, _, _ = self.request('DELETE', '/api/forms/' + created['id'])
        self.assertEqual(code, 200)
        self.assertEqual(len(self.app.forms()), 4)
        self.assertNotEqual(self.request('POST', '/api/forms', payload)[0], 201)

    def test_client_schema_is_not_trusted(self):
        code, form, _ = self.request('POST', '/api/forms', {'name': 'Draft',
            'url': 'https://forms.office.com/Pages/ResponsePage.aspx?id=synthetic-draft',
            'schema': web.normalized_schema(web.sample_schema()), 'answers': {'q0': 'Example', 'q1': 'Option A'}})
        self.assertEqual(code, 201)
        self.assertFalse(form['configured'])
        self.assertTrue(form['review_required'])

    def test_explicit_review_rejects_stale_answers_and_never_runs(self):
        original = self.app.form('F01')
        _, changed, _ = self.request('PUT', '/api/forms/F01', {'answers': dict(original['answers'], q0='Changed example')})
        self.assertEqual(self.request('POST', '/api/forms/F01/approve', {'review_token': original['review_token']})[0], 409)
        with patch.object(self.app, 'run_once', side_effect=AssertionError('approval ran forms')):
            code, approved, _ = self.request('POST', '/api/forms/F01/approve', {'review_token': changed['review_token']})
        self.assertEqual(code, 200)
        self.assertFalse(approved['review_required'])
        self.assertEqual(self.app.status()['counts']['submitted'], 0)

    def test_demo_run_does_not_open_browser_or_launch_real_runner(self):
        with patch.object(web.BrowserSession, '__enter__', side_effect=AssertionError('browser')), patch.object(web.subprocess, 'run', side_effect=AssertionError('runner')):
            code, result, _ = self.request('POST', '/api/run', {})
            self.assertEqual(code, 200)
            self.assertEqual(result['counts']['submitted'], 4)
            self.assertFalse(result['can_run'])
            self.request('POST', '/api/run', {})
            self.assertEqual(self.app.status()['counts']['submitted'], 4)

    def test_arbitrary_exception_text_never_returned(self):
        with patch.object(self.app.store, 'get_form', side_effect=ValueError('DO_NOT_EXPOSE')):
            _, result, _ = self.request('GET', '/api/forms/F01')
        self.assertNotIn('DO_NOT_EXPOSE', json.dumps(result))

    def test_sync_is_read_only(self):
        before = (self.root / 'config' / 'calendar.json').read_bytes()
        _, data, _ = self.request('POST', '/api/sync/check', {})
        self.assertFalse(data['applied'])
        self.assertEqual(before, (self.root / 'config' / 'calendar.json').read_bytes())

    def test_schedule_pause_and_review_before_opt_in(self):
        code, paused, _ = self.request('POST', '/api/forms/F01/schedule', {'scheduled': False})
        self.assertEqual(code, 200)
        self.assertFalse(paused['scheduled'])
        self.request('PUT', '/api/forms/F01', {'answers': dict(paused['answers'], q0='New example')})
        self.assertEqual(self.request('POST', '/api/forms/F01/schedule', {'scheduled': True, 'review_token': paused['review_token']})[0], 409)
        changed = self.app.form('F01')
        self.request('POST', '/api/forms/F01/approve', {'review_token': changed['review_token']})
        self.assertEqual(self.request('POST', '/api/forms/F01/schedule', {'scheduled': True, 'review_token': changed['review_token']})[0], 200)

    def test_new_template_is_unscheduled_and_refresh_preserves_answers(self):
        url = 'https://forms.office.com/Pages/ResponsePage.aspx?id=synthetic-template'
        _, inspected, _ = self.request('POST', '/api/forms/inspect', {'url': url})
        _, created, _ = self.request('POST', '/api/forms', {'name': 'Template example', 'url': url,
            'inspect_token': inspected['inspect_token'], 'answers': {'q0': 'Example', 'q1': 'Option A'}})
        self.assertFalse(created['scheduled'])
        _, refreshed, _ = self.request('POST', '/api/forms/inspect', {'url': url, 'form_id': created['id']})
        self.assertEqual(refreshed['answers']['q0'], 'Example')
        self.assertEqual(refreshed['answers']['q1'], 'Option A')
        self.request('POST', '/api/run', {})
        self.assertIsNone(web.StateStore(self.app.state_dir, web.today()).read(created['id']))

    def test_today_has_stable_school_day_schedule(self):
        _, first, _ = self.request('GET', '/api/today')
        _, second, _ = self.request('GET', '/api/today')
        self.assertEqual([item['scheduled_time'] for item in first['items']], [item['scheduled_time'] for item in second['items']])
        self.assertEqual(first['schedule_window'], '12:00–15:30 America/Chicago')

    def test_submit_one_unscheduled_form_without_running_others_or_enrolling(self):
        self.request('POST', '/api/forms/F01/schedule', {'scheduled': False})
        with patch.object(web.BrowserSession, '__enter__', side_effect=AssertionError('demo browser')):
            code, result, _ = self.request('POST', '/api/forms/F01/submit', {})
        self.assertEqual(code, 200)
        self.assertTrue(result['submitted'])
        self.assertFalse(result['form']['scheduled'])
        self.assertFalse(result['form']['can_submit'])
        state = web.StateStore(self.app.state_dir, web.today())
        self.assertEqual(state.read('F01')['status'], 'submitted')
        self.assertIsNone(state.read('F02'))
        self.assertEqual(self.request('POST', '/api/forms/F01/submit', {})[0], 409)

    def test_unreviewed_form_cannot_submit_or_launch_runner(self):
        form = self.app.form('F01')
        self.request('PUT', '/api/forms/F01', {'answers': dict(form['answers'], q0='Changed example')})
        with patch.object(web.subprocess, 'run', side_effect=AssertionError('runner must not launch')):
            code, result, _ = self.request('POST', '/api/forms/F01/submit', {})
        self.assertEqual(code, 409)
        self.assertEqual(result['error']['code'], 'review_answers_before_submitting')

    def test_claimed_or_uncertain_form_cannot_be_resubmitted_manually(self):
        from outputs.formfiller.state import _atomic_json
        state = web.StateStore(self.app.state_dir, web.today())
        _atomic_json(state.day_dir / 'schedule.json', {'claimed': ['F01']})
        self.assertFalse(self.app.form('F01')['can_submit'])
        self.assertEqual(self.request('POST', '/api/forms/F01/submit', {})[0], 409)
        state.bind_config('F02', web._config_fingerprint(self.app.store.get_form('F02')))
        state.transition('F02', 'pending', 'submitting')
        state.transition('F02', 'submitting', 'uncertain')
        self.assertEqual(self.request('POST', '/api/forms/F02/submit', {})[0], 409)

    def test_private_selected_submission_verifies_snapshot_and_uses_runner_lock(self):
        from types import SimpleNamespace
        self.app.mode = 'private'
        self.app.installed_root = self.root / 'synthetic-installed'
        def run_child(*args, **kwargs):
            state = web.StateStore(self.app.state_dir, web.today())
            # The parent must release the file lock before starting the child.
            with state.lock():
                state.bind_config('F01', web._config_fingerprint(self.app.store.get_form('F01')))
                state.transition('F01', 'pending', 'submitting')
                state.transition('F01', 'submitting', 'submitted')
            return SimpleNamespace(returncode=0, stdout=b'')
        with patch.object(web, 'verify_installation') as verify, patch.object(web.subprocess, 'run', side_effect=run_child) as child:
            code, result, _ = self.request('POST', '/api/forms/F01/submit', {})
        self.assertEqual(code, 200)
        verify.assert_called_once_with(self.app.installed_root)
        self.assertEqual(child.call_args.args[0][-3:], ['--live', '--form', 'F01'])
        self.assertTrue(result['submitted'])

    def test_private_selected_submission_reports_calendar_blocker_without_leaking_output(self):
        from types import SimpleNamespace
        self.app.mode = 'private'
        self.app.installed_root = self.root / 'synthetic-installed'
        blocked = SimpleNamespace(returncode=2, stdout=b'error code=calendar_stale\nSYNTHETIC_PRIVATE_MARKER\n')
        with patch.object(web, 'verify_installation'), patch.object(web.subprocess, 'run', return_value=blocked):
            code, result, _ = self.request('POST', '/api/forms/F01/submit', {})
        self.assertEqual(code, 409)
        self.assertEqual(result['error']['code'], 'calendar_stale')
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', json.dumps(result))

    def test_form_prefills_last_confirmed_answers_after_restart_and_on_next_day(self):
        from datetime import timedelta
        original = self.app.form('F01')['answers']
        self.request('POST', '/api/forms/F01/submit', {})
        restarted = web.WebApp(self.app.config_dir, self.app.state_dir, self.app.profile_dir)
        with patch.object(web, 'today', return_value=web.today() + timedelta(days=1)):
            form = restarted.form('F01')
        self.assertEqual(form['answer_source'], 'last_submission')
        self.assertEqual(form['answers'], original)
        self.assertEqual(form['answers']['q2'], {'kind': 'date'})
        self.assertTrue(form['can_submit'])
        self.assertIsNotNone(form['last_submitted_on'])
        self.assertIsNone(restarted.form('F02')['last_submitted_on'])

    def test_unsent_edits_preserved_and_last_submission_stays_private(self):
        self.request('POST', '/api/forms/F01/submit', {})
        old = self.app.form('F01')
        _, saved, _ = self.request('PUT', '/api/forms/F01', {'answers': dict(old['answers'], q0='Unsent synthetic draft')})
        self.assertEqual(saved['answer_source'], 'saved_changes')
        self.assertEqual(saved['answers']['q0'], 'Unsent synthetic draft')
        snapshot = self.app.store.get_form('F01')['last_submission']
        self.assertEqual(snapshot['answers'][0]['value'], 'Example answer')
        runtime_contents = '\n'.join(path.read_text() for path in self.app.state_dir.rglob('*.json'))
        self.assertNotIn('Example answer', runtime_contents)
        self.assertNotIn('Unsent synthetic draft', runtime_contents)

    def test_schema_refresh_uses_last_submission_by_title_without_changing_approvals(self):
        from copy import deepcopy
        original = self.app.store.get_form('F01')
        effective = deepcopy(original)
        effective['schema']['questions'].reverse()
        effective['answers'].reverse()
        self.app.store.record_submission('F01', effective, web.today(), web._config_fingerprint(original))
        _, refreshed, _ = self.request('POST', '/api/forms/inspect', {'url': original['url'], 'form_id': 'F01'})
        self.assertEqual(refreshed['answers']['q0'], 'Example answer')
        self.assertEqual(refreshed['answers']['q1'], 'Option A')
        self.assertFalse(self.app.form('F01')['review_required'])

    def setup_picker(self):
        install = self.root / 'installed'
        install.mkdir()
        (install / 'install-manifest.json').write_text(json.dumps({'source_root': str(self.root / 'source')}))
        app = web.WebApp(self.root / 'placeholder', self.root / 'runtime' / 'state',
            self.root / 'runtime' / 'browser-profile', mode='private', installed_root=install, needs_setup=True)
        workspace = self.root / 'chosen'
        workspace.mkdir()
        return app, workspace

    def test_first_launch_chooses_folder_without_live_enablement(self):
        app, workspace = self.setup_picker()
        with patch('tkinter.Tk'), patch('tkinter.filedialog.askdirectory', return_value=str(workspace)), patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'local')}):
            result = app.choose_workspace()
        self.assertFalse(result['needs_setup'])
        self.assertEqual(app.forms(), [])
        self.assertIs(json.loads((workspace / 'config' / 'settings.json').read_bytes())['live_enabled'], False)
        self.assertNotIn(str(workspace), json.dumps(result))

    def test_cancelled_picker_creates_no_configuration(self):
        app, workspace = self.setup_picker()
        with patch('tkinter.Tk'), patch('tkinter.filedialog.askdirectory', return_value=''):
            self.assertTrue(app.choose_workspace()['cancelled'])
        self.assertFalse((workspace / 'config').exists())

    def test_picker_locator_failure_rolls_back_new_configuration_and_owner(self):
        app, workspace = self.setup_picker()
        from outputs.formfiller import state
        original = state._atomic_json
        def fail_locator(path, value):
            if path.name == 'paths.json':
                raise OSError('synthetic failure')
            return original(path, value)
        with patch('tkinter.Tk'), patch('tkinter.filedialog.askdirectory', return_value=str(workspace)), patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'local')}), patch.object(state, '_atomic_json', side_effect=fail_locator):
            with self.assertRaisesRegex(web.WebError, '^workspace_setup_failed$'):
                app.choose_workspace()
        self.assertTrue(app.needs_setup)
        self.assertEqual(list((workspace / 'config').iterdir()), [])
        self.assertFalse((workspace / '.formfiller-owner.json').exists())

    def test_picker_never_adopts_unowned_submission_history(self):
        app, workspace = self.setup_picker()
        app.state_dir.mkdir(parents=True)
        history = app.state_dir / '2026-10-02'
        history.mkdir()
        with patch('tkinter.Tk'), patch('tkinter.filedialog.askdirectory', return_value=str(workspace)):
            with self.assertRaisesRegex(web.WebError, '^existing_runtime_requires_review$'):
                app.choose_workspace()
        self.assertFalse((workspace / 'config').exists())

    def test_static_headers_and_no_path_traversal(self):
        code, _, headers = self.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('GET', '/../../config/forms.json')[0], 404)


if __name__ == '__main__':
    unittest.main()
