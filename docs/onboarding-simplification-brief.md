# Brief: simpler install and onboarding for new teachers

FormFiller is a **single-PC** app. A copy of it running on a second computer for the same user is unsupported and unsafe. Existing installations are not changed by this work.

## Ground rules
- Never run the real installer, launcher, scheduler registration, or a live submission on the development machine. Verify with the mocked-root tests, synthetic data, and a manual checklist for the owner. No Sandbox or VM is available.
- Do not touch private workspaces or `%LOCALAPPDATA%\FormFiller` on the dev machine. Tests use temporary roots only.
- Existing installations keep their current workspace, runtime, approvals and state. Only new installs get the new defaults. No auto-migration.
- Never add a path that submits a response, enables live mode, or approves anything without an explicit user action.
- Run `tools.audit_privacy --staged` before committing. Update `AGENTS.md`, the README and the guide wherever behavior changes (see Calendar).

## Decisions already made
- Data lives in `%LOCALAPPDATA%\FormFiller\data` for new installs. It is created silently, with no folder picker and no sync provider involved. Config, state and the browser profile all live under it. The installed snapshot stays separate, so updates never touch data.
- Multi-PC handling: warn in the docs and in the UI. Keep the existing owner binding. Do not add detection or blocking.
- Moving PCs: add Export/Import of forms and settings only. The export excludes sign-in data, submission state, locks, approvals and the calendar. The import prompts for re-review and re-approval of answers on the new PC.
- Form name: when the user supplies a URL and the form is inspected, set the name to the pulled Form title. **Refresh questions / URL** updates the name unless the user has renamed it. Track this with a flag, for example `name_custom`. A rename sets the flag. Typed names are only a fallback when no title could be pulled.
- District-specific defaults remain, but no district name appears in user-facing text or source; use neutral wording such as "school calendar".

## Work items

### 1. Settings (new Settings view, persisted in `settings.json`)
- Submit window start and end (default 12:00 PM and 3:30 PM) and time zone (default America/Chicago). Replace the hardcoded values in `scheduling.py`, `windows_schedule.py` and `Install-SchoolDaySchedule.ps1`. Validate the values: start before end, valid IANA zone.
- Calendar format defaults (standard SchoolDays headers `Title`, `SchoolDate`, `DayOfWeek`, `DayType` pre-filled, overridable). Detect the standard format from the file and skip the manual header and timestamp entry when it matches.
- Changing the window or time zone refreshes the scheduled tasks. It never submits.
- Tests: settings validation, window and time-zone effects on slot planning, and task reconciliation.

### 2. Data location without a picker
- New installs resolve workspace and runtime to the per-user data directory above. Keep `paths.json` as the locator and keep the existing resolution for installations that already have one.
- Remove the first-run folder picker from the new-install path. This also removes the tkinter requirement. Replace the native file dialog for calendar import with a browser file upload.
- Tests: fresh-install resolution with a temporary root, an existing-locator install unchanged, and no tkinter import on the new path.

### 3. Shipped default calendar
- Ship the sanitized date-only calendar as `outputs/formfiller/default_calendar.py` with the installed snapshot (implemented; private calendars override it), labeled with its school year and coverage.
- First run offers one action: **Review and confirm district calendar**. It shows every instructional date and the coverage range. The user must explicitly confirm that it matches the district calendar. Nothing is pre-approved.
- Keep importing the user's own workbook as the alternative.
- Coverage ends at the school year's end. A new school year needs a newly shipped or imported calendar.
- This changes a rule in `AGENTS.md` ("each installation must obtain the user's own reviewed calendar"). Update it. State that the shipped calendar is a default the user confirms and never an inherited approval from another user.
- Tests: the confirmation is required, nothing is approved by installing, and out-of-coverage dates still block.

### 4. Form name from Form title
- Pull the title during inspect and set the name. Rename sets the custom flag. Refresh updates the name only when the flag is unset.
- Tests: title used, rename preserved across refresh, fallback when no title.

### 5. First-run wizard
- A single guided flow in order: confirm calendar, add a form URL, sign in to Edge manually, review answers, enable live submissions. Show progress and a final "ready" screen. Keep each safety gate as it is today.
- Show a visible single-PC notice and the Export/Import actions under Settings.
- Tests: step gating, no skipping of approvals, and sanitized output.

### 6. Install and docs
- Map install error codes (`execution_policy_blocked`, `install_failed`, `python_312_required`, `windows_x64_required` and others) to plain-language steps in the guide.
- Split the README: a short user quick-start with screenshots (synthetic data only) and a separate developer and privacy document.
- Have `.githooks/pre-commit` fall back to a working Python when `outputs/.venv` is broken.
- Add an update notice or a single-click update so `-Update` isn't required from PowerShell.

### 7. Verification
- All existing and new tests pass, including the installer tests with isolated roots.
- Provide the owner a manual checklist for a clean Windows account: install, shortcut, first-run wizard, calendar confirmation, form add, sign-in, answer review, settings change, export and import. Mark which parts cannot be covered without a clean machine.

## Order
1, 4 and 2 are independent and small. Do 3 after 2. Do 5 after 1–4. Docs (6) last.
