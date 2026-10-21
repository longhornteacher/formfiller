# FormFiller agent instructions

## Installing for a new user

When a user points an agent at an empty folder and says "install this" with this GitHub repository link, complete the installation, including the desktop shortcut. Clone the repository into the chosen folder (use `git clone <user-provided-repository-url> .` only when it is empty), read these instructions, and run:

```powershell
powershell.exe -NoProfile -File .\Install.ps1
```

`Install.ps1` reuses suitable PowerShell 7 and Python 3.11+ runtimes or installs pinned, vendor-verified per-user packages, and uses the official Windows package manager for a missing Microsoft Edge, builds and validates a clean installed snapshot outside the checkout, installs application dependencies, registers background school-day dispatch, creates **Launch FormFiller** with its own checklist icon on the user's actual Desktop, and opens the local WebUI. The shortcut and installed application work after the source clone is moved or removed. `-NoLaunch` installs without opening the UI. `-NoPrerequisiteInstall` reports missing prerequisites instead of installing them. Installation is Windows-only; if device policy, OS consent, or a missing package manager blocks a prerequisite, report that specific blocker. Never bypass policy, authentication, or execution-policy restrictions.

Treat "install this" as authorization to perform this setup; do not stop after cloning, hand the user a list of commands, or ask again before creating the requested shortcut. Verify the sanitized `status=installed` result and that the shortcut exists. Do not operate private UI pages through agent browser tools. The user chooses the private workspace, signs in manually, enters and reviews answers, and provides a reviewed school calendar in the local application. Installing is not authorization to invent or approve these inputs, enable live mode, or submit responses. Background dispatch stays dormant until workspace selection and remains blocked until all live prerequisites pass.

Re-running setup reuses and verifies the existing installed snapshot, workspace, and runtime; it must not reset submission history, silently replace an invalid snapshot, or rebind an owner. An existing older installation that lacks the new scheduler needs a separately reviewed snapshot update. Application updates must keep existing private data and approvals.

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
- The user designated `Pearland_2026-27_Instructional_Dates_Full_Text.xlsx` as the actual district school calendar on October 1, 2026. Migration relocated it to the private workspace's `sources` folder, preserving its approval, hash, freshness date, and 171 reviewed `SchoolDays`, including two early-release instructional days. The normalized snapshot is the private workspace's `config/calendar.json`; only listed dates permit submission. Dates omitted from its complete coverage are non-school days. Missing/changed/stale sources or dates outside coverage must stop the run before Forms opens. A weekday scheduler trigger never establishes that a date is instructional.
- That calendar approval applies only to the existing teacher workspace. New installations must obtain the user's own reviewed school calendar; never copy another user's runtime approval, settings, forms, or answers into a new installation.
- Live runs require `live_enabled=true`, a fresh approved district workbook snapshot (or a reviewed SharePoint `SchoolDays` export), manually authenticated dedicated Edge profile, and reviewed schema approvals. If prerequisites are missing, report the specific blocker. Do not change settings, approve schemas/calendars, freshen timestamps, or edit configured answers to get a run past a blocker.
- Run once. Do not automatically retry, use `--resume`, delete locks/state, resubmit uncertain records, edit the runner, or bypass district authentication/security controls during an operating request.
- A scheduled run must use the verified installed snapshot and the one designated local runtime's persistent state, with this Windows account logged in. Existing local wrappers forward to that snapshot. Cloud-only runs cannot launch the local tool. Never fall back to a cloud browser or copy form configuration to an agent/cloud browser. The user-selected workspace may sync through its existing folder provider; authentication, locks, and submission state must remain outside that synced folder. Never automatically rebind a runtime owner.
- For scheduled runs, stay quiet on an ordinary non-school-day skip or unchanged blocked status. Notify on a completed run, a new failure/blocker, or required user action. Keep all details sanitized. No external messages or email are authorized.
- Development/testing must not submit live responses. Use the existing tests and local mock forms. A request to improve the code is not a request for a live run.
- File separation alone does not restrict a host agent. Use the clean bundle in a separate VM/account with no private mounts or credentials for enforced isolation. The supplied Windows Sandbox definition is usable only if Windows Sandbox is installed; it does not constrain the current host session.
- Before committing or pushing, audit the exact staged files with `outputs/.venv/Scripts/python.exe -m tools.audit_privacy --staged` and review all data/fixtures for real names. The district calendar is allowed in Git; the date-only reference under `calendar/` is sanitized for that purpose. Keep private configuration, answers, observed schemas, credentials, browser data, and submission state out of Git, including forced additions. Enable the local hook with `git config core.hooksPath .githooks`.
