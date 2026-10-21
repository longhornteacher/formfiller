import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from outputs.formfiller import run_and_check
from outputs.formfiller.workspace import WorkspacePaths


class RunAndCheckTests(unittest.TestCase):
    def invoke(self, runner_code=0, monitor_code=0, args=None):
        workspace=WorkspacePaths(Path('fixture-root/config'),Path('fixture-root/state'),Path('fixture-root/runtime/browser-profile'))
        with patch.object(run_and_check,'resolve_workspace',return_value=workspace), patch.object(run_and_check.runner,'run',return_value=runner_code) as run, patch.object(run_and_check.monitor,'main',return_value=monitor_code) as check, contextlib.redirect_stdout(io.StringIO()):
            code=run_and_check.main(args or [],root=Path('fixture-root'))
            return code,run.call_args_list,check.call_args_list

    def test_run_once_then_check(self):
        code,runs,checks=self.invoke()
        self.assertEqual(code,0)
        self.assertEqual(len(runs),1)
        self.assertEqual(len(checks),1)
        self.assertIn('--live',runs[0].args[0])

    def test_blocked_run_cannot_be_hidden_by_old_success(self):
        code,runs,checks=self.invoke(runner_code=2)
        self.assertEqual(code,2)
        self.assertEqual(len(runs),1)
        self.assertEqual(len(checks),1)

    def test_non_school_day_is_successful_skip(self):
        code,runs,checks=self.invoke(runner_code=3)
        self.assertEqual(code,0)
        self.assertEqual(len(runs),1)
        self.assertEqual(checks,[])

    def test_check_only_never_runs(self):
        code,runs,checks=self.invoke(args=['--check-only'])
        self.assertEqual(code,0)
        self.assertEqual(runs,[])
        self.assertEqual(len(checks),1)

    def test_incomplete_check_is_failure(self):
        code,runs,checks=self.invoke(monitor_code=1)
        self.assertEqual(code,1)
        self.assertEqual(len(runs),1)

    def test_scheduled_dispatch_does_not_report_future_slots_as_missing(self):
        code,runs,checks=self.invoke(args=['--scheduled'],monitor_code=1)
        self.assertEqual(code,0)
        self.assertEqual(len(runs),1)
        self.assertIn('--scheduled',runs[0].args[0])
        self.assertEqual(checks,[])

    def test_scheduled_failure_is_preserved_without_retry(self):
        code,runs,checks=self.invoke(args=['--scheduled'],runner_code=4)
        self.assertEqual(code,4)
        self.assertEqual(len(runs),1)
        self.assertEqual(checks,[])

    def test_migration_gate_prevents_source_forwarding(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'.migration.lock').write_text('fixture',encoding='utf-8')
            with patch.object(run_and_check.subprocess,'run') as child, contextlib.redirect_stdout(io.StringIO()):
                code=run_and_check.main(['--check-only'],root=root)
            self.assertEqual(code,run_and_check.runner.EXIT_CONFIG)
            child.assert_not_called()

    def test_source_command_forwards_to_verified_installed_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            installed=root/'installed'
            interpreter=installed/'.venv'/'Scripts'/'python.exe'
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b'fixture executable')
            workspace=WorkspacePaths(root/'private'/'config',root/'runtime'/'state',root/'runtime'/'browser-profile',True,True,installed)
            completed=type('Completed',(),{'returncode':0})()
            with patch.object(run_and_check,'resolve_workspace',return_value=workspace), patch.object(run_and_check,'validate_snapshot',return_value={'version':1,'files':1}) as validate, patch.object(run_and_check.subprocess,'run',return_value=completed) as child, contextlib.redirect_stdout(io.StringIO()):
                code=run_and_check.main(['--check-only'],root=root/'source'/'outputs')
            self.assertEqual(code,0)
            validate.assert_called_once_with(installed)
            self.assertEqual(child.call_args.args[0][1:4],['-m','formfiller.run_and_check','--check-only'])
            self.assertEqual(child.call_args.kwargs['cwd'],installed)


if __name__=='__main__':
    unittest.main()
