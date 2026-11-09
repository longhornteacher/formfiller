# FormFiller agent instructions

## Installing for a new user

When a user points an agent at an empty folder and says "install this" with this GitHub repository link, perform the whole installation below yourself, including the desktop shortcut. There is no installer script: this runbook is the installer. Do not stop after cloning, hand the user a list of commands, or ask again before creating the shortcut. Windows 10/11 x64 only; if device policy, OS consent, or a missing package manager blocks a step, report that specific blocker and never bypass policy, authentication, or execution-policy restrictions.

Use `$app = Join-Path $env:LOCALAPPDATA 'FormFiller'` for all per-user state. Run each step in order and stop at the first failure.

1. **Clone.** `git clone <user-provided-repository-url> .` only when the folder is empty. Read this file. The clone is a source checkout; it is not the installed app.
2. **Detect an existing installation.** If `$app\paths.json` or `$app\installation.json` exists, do not create a second runtime: skip to step 9 (repair shortcut) and report that the existing installation was reused. If the Codex packaged app redirected app data (`%LOCALAPPDATA%\Packages\OpenAI.Codex_*\LocalCache\Local\FormFiller\paths.json`) and exactly one such locator exists, tell the user it exists and ask before copying it; never merge several.
3. **Prerequisites** (per-user, no admin unless Edge is missing). Dot-source `tools\Bootstrap-WebUI.ps1` under Windows PowerShell 5.1 for its helpers: `Resolve-FormFillerPowerShell`, `Resolve-FormFillerPython`, `Install-FormFillerEdge`, with `$dependencyRoot = "$app\Dependencies"`. They reuse a suitable PowerShell 7 and Python 3.11-3.14 (with pip, venv, tkinter), otherwise download pinned, hash/signature-verified packages; Edge is installed through winget only if missing. Keep the returned `$shell` (pwsh) and `$python` paths.
4. **Build and install a reviewed snapshot** outside the checkout:
   ```powershell
   $snapshot = Join-Path $app ('App\snapshot-' + [Guid]::NewGuid().ToString('N').Substring(0,12))
   $artifacts = Join-Path (Get-Location) 'tools\artifacts'
   & $shell -NoProfile -File .\tools\Build-CleanSource.ps1 -RepositoryRoot . -OutputRoot $artifacts
   & $shell -NoProfile -File .\tools\Install-ReviewedSnapshot.ps1 -Destination $snapshot -SourceRoot . -SourceBundle (Join-Path $artifacts 'formfiller-clean-source') -PythonPath $python -InstallDependencies
   ```
5. **Verify** the snapshot with its own interpreter: `& "$snapshot\.venv\Scripts\python.exe" -c "import sys; sys.dont_write_bytecode=True; sys.path.insert(0, sys.argv[1]); from formfiller.deployment import validate_snapshot; validate_snapshot(sys.argv[1])" $snapshot`. A non-zero exit is the blocker `installed_snapshot_invalid`.
6. **Record the installation:** write `$app\installation.json` as `{"version":1,"installed_app":"<snapshot path>"}` (UTF-8, no BOM). Do not write `paths.json`: the app creates it when the user picks a workspace.
7. **Launcher files:** copy `tools\Open-FormFiller.ps1` to `$app\Open-FormFiller.ps1`, and build the icon: `& $shell -NoProfile -File .\tools\Build-LauncherIcon.ps1 -SourceSvg outputs\formfiller\web_static\formfiller.svg -DestinationIco "$app\FormFiller.ico"`.
8. **Daily planner:** `& $shell -NoProfile -File .\tools\Install-SchoolDaySchedule.ps1 -Snapshot $snapshot -AllowUnconfigured -PowerShellPath $shell`. It registers one windowless `\FormFiller\Daily Plan` task (about 6:00 AM Central and at sign-in) and removes the retired every-minute `FormFiller Daily 3PM` task. Each morning the planner assigns every scheduled template a random time in the submit window (default 12:00-3:30 PM America/Chicago; editable under Settings), deletes yesterday's timing and leftover tasks, and registers one run-once `\FormFiller\Run HHMM` task per slot. All tasks launch `pythonw.exe`, so only Edge is visible. It stays inert until a workspace is selected and every live prerequisite passes; non-school days register nothing.
9. **Desktop shortcut** on the user's actual Desktop (`[Environment]::GetFolderPath('DesktopDirectory')`, which may be redirected to a cloud folder), named `Launch FormFiller.lnk`, description exactly `FormFiller local WebUI`, target `$shell`, arguments `-NoProfile -WindowStyle Hidden -File "$app\Open-FormFiller.ps1"`, working directory `$app`, icon `$app\FormFiller.ico,0`, window style 7 (minimized). If a shortcut with that name exists and its description differs, stop with `desktop_shortcut_exists`; never overwrite an unrelated shortcut.
10. **Open the UI:** run `Start-Process $shell -ArgumentList '-NoProfile','-WindowStyle','Hidden','-File',"$app\Open-FormFiller.ps1"`. Confirm the shortcut file exists and the snapshot validated, then report the sanitized result only (`installed`, shortcut present, scheduler dormant).

The shortcut and installed app work after the source clone is moved or removed. Treat "install this" as authorization for these steps only. Do not operate private UI pages through agent browser tools. The user chooses the private workspace, signs in manually, enters and reviews answers, and provides a reviewed school calendar in the local application. Installing is not authorization to invent or approve these inputs, enable live mode, or submit responses.

**Updating** requires an explicit user request. Validate the current snapshot first (step 5 against `installation.json`; never repair or replace an invalid one), then repeat steps 4-5 into a new snapshot directory, switch `installed_app` in `paths.json` (when present) and `installation.json` only after the new snapshot validates, rerun step 8 with `-Snapshot <new>`, and keep a copy of the old values so a failure restores them. Never delete an existing runner lock, reset submission history, change the workspace, or rebind a runtime owner.

## Operating an existing installation

When the user says "run it", "run today's forms", or "run it and check logs", run the reviewed local tool and verify its sanitized status:

```powershell
$locator = Join-Path $env:LOCALAPPDATA 'FormFiller\paths.json'
$mapping = Get-Content -LiteralPath $locator -Raw | ConvertFrom-Json
& (Join-Path $mapping.installed_app 'Run-FormFillerOperation.ps1')
```

For "check logs" or "check status" without a request to submit, add `-CheckOnly`. Do not print the locator's contents. If it is absent, report `workspace_required` and direct the user to the desktop shortcut; do not fall back to editable source.

The command is now a compatibility launcher. It validates and forwards to the installed snapshot named by the local workspace locator; never substitute the editable runner for a missing or changed snapshot. `outputs/OpenForms.bat` opens that installed local UI, and `outputs/DemoForms.bat` opens a synthetic development preview.

- The user-approved fixed answers and form URLs are only in the selected private workspace's `config/forms.json`. The local locator is `%LOCALAPPDATA%\FormFiller\paths.json`. Do not print private configuration, student names, page content, or browser profile data in chat, logs, scheduled prompts, or notifications. Do not open private UI pages using agent browser tools. Use synthetic demo data for UI inspection.
- Keep the deterministic runner responsible for browser interactions, calendar checks, field checks, and duplicate protection. Report date, aliases, sanitized codes, and counts only.
- The school calendar defaults to the built-in, date-only 2026-27 calendar in `outputs/formfiller/default_calendar.py` (171 instructional days, including two early-release days; the project owner designated it as the default). A private workspace `config/calendar.json` takes precedence when present. Only listed dates permit submission; dates omitted from complete coverage are non-school days. A private calendar that is present but missing its source, changed, stale, unapproved, or invalid must stop the run before Forms opens and never falls back to the built-in one. Dates outside the active calendar's coverage also stop the run. A weekday scheduler trigger never establishes that a date is instructional.
- The existing teacher workspace keeps its own reviewed private calendar approval. Never copy another user's runtime approval, settings, forms, or answers into a new installation; new installations use the built-in calendar unless the user imports and reviews their own.
- Live runs require `live_enabled=true`, a school calendar covering the run date (the built-in calendar, or the user's reviewed private one), manually authenticated dedicated Edge profile, and reviewed schema approvals. If prerequisites are missing, report the specific blocker. Do not change settings, approve schemas/calendars, freshen timestamps, or edit configured answers to get a run past a blocker.
- Run once. Do not automatically retry, use `--resume`, delete locks/state, resubmit uncertain records, edit the runner, or bypass district authentication/security controls during an operating request.
- A scheduled run must use the verified installed snapshot and the one designated local runtime's persistent state, with this Windows account logged in. Existing local wrappers forward to that snapshot. Cloud-only runs cannot launch the local tool. Never fall back to a cloud browser or copy form configuration to an agent/cloud browser. The user-selected workspace may sync through its existing folder provider; authentication, locks, and submission state must remain outside that synced folder. Never automatically rebind a runtime owner.
- For scheduled runs, stay quiet on an ordinary non-school-day skip or unchanged blocked status. Notify on a completed run, a new failure/blocker, or required user action. Keep all details sanitized. No external messages or email are authorized.
- Development/testing must not submit live responses. Use the existing tests and local mock forms. A request to improve the code is not a request for a live run.
- File separation alone does not restrict a host agent. Use the clean bundle in a separate VM/account with no private mounts or credentials for enforced isolation. The supplied Windows Sandbox definition is usable only if Windows Sandbox is installed; it does not constrain the current host session.
- Before committing or pushing, audit the exact staged files with `outputs/.venv/Scripts/python.exe -m tools.audit_privacy --staged` and review all data/fixtures for real names. The district calendar is allowed in Git; the date-only reference under `calendar/` is sanitized for that purpose. Keep private configuration, answers, observed schemas, credentials, browser data, and submission state out of Git, including forced additions. Enable the local hook with `git config core.hooksPath .githooks`.
