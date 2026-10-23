"""Single command for an operator/agent: run once, then check sanitized status."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import monitor, runner, scheduling
from .workspace import WorkspaceError, resolve_workspace
from .deployment import DeploymentError, validate_snapshot


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None, *, root=ROOT):
    original_args = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Read status only; never open or submit forms.')
    parser.add_argument('--scheduled', action='store_true', help='Process only due templates in the daily window.')
    args = parser.parse_args(argv)
    if args.scheduled and args.check_only:
        parser.error('--scheduled cannot be combined with --check-only')
    root = Path(root)
    if (root / '.migration.lock').exists():
        print('error code=migration_in_progress', flush=True)
        return runner.EXIT_CONFIG
    try:
        workspace = resolve_workspace(root)
    except WorkspaceError as exc:
        print(f'error code={exc.code}', flush=True)
        return runner.EXIT_CONFIG
    is_default_root = root.resolve() == ROOT.resolve()
    installed_app = workspace.installed_app
    if installed_app is not None and root.resolve() != installed_app.resolve():
        # Source checkouts may launch only the verified installed snapshot.
        try:
            validate_snapshot(installed_app)
            interpreter = installed_app / '.venv' / 'Scripts' / 'python.exe'
            if not interpreter.is_file():
                interpreter = installed_app / '.venv' / 'bin' / 'python'
            if not interpreter.is_file():
                raise DeploymentError('installed_python_missing')
            child_env = os.environ.copy()
            child_env['FORM_FILLER_WORKSPACE'] = str(workspace.config_dir.parent)
            child_env['FORM_FILLER_RUNTIME'] = str(workspace.state_dir.parent)
            child_env['PYTHONDONTWRITEBYTECODE'] = '1'
            result = subprocess.run(
                [str(interpreter), '-m', 'formfiller.run_and_check', *original_args],
                cwd=installed_app, env=child_env, check=False,
            )
            return int(result.returncode)
        except DeploymentError as exc:
            print(f'error code={exc.code}', flush=True)
            return runner.EXIT_CONFIG
        except OSError:
            print('error code=installed_runner_unavailable', flush=True)
            return runner.EXIT_CONFIG
    if installed_app is not None and is_default_root and not args.check_only:
        try:
            validate_snapshot(installed_app, current_file=Path(__file__))
            sys.dont_write_bytecode = True
        except DeploymentError as exc:
            print(f'error code={exc.code}', flush=True)
            return runner.EXIT_CONFIG
    scheduling.apply_from_config(workspace.config_dir)
    day = scheduling.now().date().isoformat()
    run_code = 0
    if not args.check_only:
        run_code = runner.run([
            '--live', '--config-dir', str(workspace.config_dir), '--state-dir', str(workspace.state_dir),
            *(['--scheduled'] if args.scheduled else []),
        ], project_root=root)
        print(f'run_exit={run_code}', flush=True)
        if run_code == runner.EXIT_NOT_SCHOOL_DAY:
            print(f'{day}: status=skipped_non_school_day', flush=True)
            return 0
        if args.scheduled:
            # Future slots are intentionally pending. The final status check is
            # available separately after the afternoon window.
            return run_code
    # Force an immediate check for the run date, even before the scheduled due time.
    check_code = monitor.main([
        '--calendar', str(workspace.config_dir/'calendar.json'), '--forms', str(workspace.config_dir/'forms.json'),
        '--state-dir', str(workspace.state_dir), '--date', day,
    ])
    print(f'check_exit={check_code}', flush=True)
    return run_code or check_code


if __name__ == '__main__':
    raise SystemExit(main())
