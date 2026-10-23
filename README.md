# FormFiller

**All your forms in one place!**

Keep your go-to forms together, fill in and save your answers, and submit a form when you're ready. Scheduling is optional: enable it for forms you want submitted automatically on school days.

Each form starts with the answers from its last confirmed FormFiller submission. Newer saved edits take precedence so unfinished work is preserved. The editor shows where the answers came from and the last submission date. Run-date fields still use the current approved run date. A form without a recorded submission uses its saved answers; earlier submissions made outside FormFiller are not imported automatically.

Your forms and answers stay in a private workspace. The editable checkout is for development; submissions use a reviewed installed snapshot and its designated private runtime.

Last-submission contents are kept only with that form in private `config/forms.json`, including the actual schema and values submitted. Failed, preview-only, and uncertain attempts never replace them. Confirmed submissions remain confirmed if saving these defaults fails; that failure never triggers a resubmission. Runtime logs and state retain sanitized aliases, dates, codes, counts, and fingerprints only.

## Install with an agent

Point a Windows agent at an empty folder and say:

> Install this: https://github.com/longhornteacher/formfiller

There is no installer to run. The agent clones the repository, reads `AGENTS.md`, and follows its install runbook: it reuses or fetches verified per-user PowerShell and Python, installs a missing Microsoft Edge through winget, builds a reviewed snapshot with its own Python environment, registers the dormant background school-day scheduler, places a **Launch FormFiller** shortcut with a custom checklist icon on your Desktop, and opens the WebUI. No manual Python or PowerShell setup is needed when Windows permits the prerequisite installation.

Double-click **Launch FormFiller** on your Desktop whenever you want to open it. The shortcut launches the local WebUI in your default browser without a terminal window and works independently of the downloaded source folder. If you close the folder picker without choosing a folder, the shortcut asks again next time; nothing is reinstalled. Asking the agent to install again reuses the current installation and repairs its shortcut, preserving unrelated shortcuts. It does not reset private data or silently upgrade an installed snapshot.

On first use, choose a private workspace, add and review your form templates, and complete the Readiness checks. School-calendar review and dedicated Edge sign-in remain explicit user steps. Installation creates no approvals and submits no forms. The background task waits for workspace selection and all live prerequisites. If organization policy blocks software installation or scheduled tasks, the agent stops and reports that blocker so IT can resolve it.

To update, ask the agent explicitly. It validates the current snapshot, installs a fresh one, and switches the launcher and scheduler while retaining the same private workspace, approvals, profile, and submission state; a failed switch restores the previous locator and an existing runner lock is never removed.

## Repository privacy

Source repository: [longhornteacher/formfiller](https://github.com/longhornteacher/formfiller).

Only source, documentation, synthetic tests, and the date-only district reference in `calendar/` belong in Git. Private form URLs, saved answers, observed schemas, browser authentication, configuration, run state, reports, credentials, and user-specific paths stay outside the commit set. The district calendar reference is permitted; it does not grant runtime approval or refresh production calendar dates.

Enable the staged-file check in each clone:

```powershell
git config core.hooksPath .githooks
& 'outputs/.venv/Scripts/python.exe' -m tools.audit_privacy --staged
```

The hook audits actual staged contents, including forced additions, and emits only finding codes. It blocks private file paths, personal paths, emails, phone/SSN shapes, secret patterns, non-synthetic Forms links, and unreviewed binary files. Pattern checks cannot identify every person's name; keep all fixtures fictional and review new documents or data manually before staging them.

## Local UI

Use the **Launch FormFiller** desktop shortcut after installation. `LaunchWebUI.bat` in the repository remains a development/compatibility launcher; it uses the existing installed app when configured and otherwise prepares a runtime. Keep that compatibility launcher's window open while using it. `outputs/OpenForms.bat` also forwards to it. The desktop shortcut runs independently in the background.

If Codex's packaged Windows app created the original installation in its redirected app-data folder, the install agent finds that existing locator and asks before copying it, so the same private workspace and local submission state are kept. It never creates a second runtime or resets approvals.

Forms is the default view: find a saved form, fill in its answers, save, review, and choose **Fill & submit**. You can submit one reviewed form without scheduling it. Changed answers require an explicit review before submission. The collapsed **Scheduling (optional)** section offers **Add to schedule** and **Pause schedule**. Today, History, Sync, and Readiness are secondary navigation views. Sync checks local source validity; the selected folder's sync provider handles file transfer. FormFiller does not refresh calendar approval dates during a sync check.

### Templates and school-day scheduling

Paste a Microsoft Forms URL and choose **Inspect form** to import its questions locally. Fill in the answers, save, and review them. **Fill & submit** submits just that form, with school-calendar validation, reviewed answers, and duplicate protection. It does not enroll the form in a schedule. For automatic submission, expand **Scheduling (optional)** and choose **Add to schedule**. **Pause schedule** keeps a template for later; **Remove form** archives it while preserving history. Existing templates without a scheduling flag keep their prior scheduled behavior when upgrading. New templates are unscheduled until explicitly added. Editing answers requires another review before that template can submit. Renaming or pausing does not reset submission history.

Each school morning a planner task (about 6:00 AM Central, also at sign-in if the PC was off) gives every scheduled template a random time between the submit window start and end (default **12:00 PM and 3:30 PM America/Chicago**; editable under Settings, which also refreshes the tasks and never submits), deletes yesterday's timing, and registers one run-once Windows task per slot. Nothing runs between slots, so ten forms mean ten launches. Tasks start `pythonw.exe` (no console window); only Edge appears while a form is submitted. The daily plan and attempt claims live in the designated local runtime, outside the synced workspace. Restarting the app, editing templates, and adding or removing other forms do not reshuffle existing slots. Adding or pausing a schedule in the WebUI updates today's tasks right away: a late addition receives a time in the remaining window, or waits until the next school day if the window has closed. The computer must remain awake with this Windows account logged in. A slot missed while the PC slept runs on wake if the window is still open; nothing is submitted after 3:30 PM. Claims, failures, and uncertain outcomes are never automatically retried that day. A task that finds the shared lock busy waits for it (up to 20 minutes) before dispatching, since nothing is claimed before the lock.

Today shows the assigned times. A manual **Run today's forms** runs the scheduled templates immediately; template-only and paused forms stay excluded. Calendar validity, explicit answer/schema review, runtime ownership, sign-in, the shared lock, and durable submission state remain mandatory.

When the live form changes, the runner preserves answers by unique question title rather than question position. It leaves new options unselected and drops removed options/questions when the remaining answer plan is valid. New optional questions can remain blank. Ambiguous questions, changed input types or requiredness, a removed required answer, or an unanswered required question/matrix row require review of that template. The editor shows a persistent warning; **Refresh questions / URL** imports the latest version and carries forward matching answers for review. A template with a schema mismatch does not block other due templates in background dispatch. No replacement answers are invented and no approvals are granted automatically.

After reviewing and installing a snapshot containing these changes, replace the existing every-minute Windows task with the daily planner:

```powershell
pwsh -NoProfile -File .\tools\Install-SchoolDaySchedule.ps1 -Snapshot '<reviewed installed snapshot>'
```

This validates the installed snapshot and designated runtime owner, registers `\FormFiller\Daily Plan`, and deletes the retired `FormFiller Daily 3PM` task. The planner and run-once tasks use `pythonw.exe` with `-B` and log only sanitized codes to `background.log` in the local runtime. The scheduler does not submit responses, change the selected workspace, enable live mode, refresh calendar approvals, or rebind runtime ownership. Only the designated installed snapshot may register tasks; the development checkout and demo never touch Task Scheduler. Run this standalone installer only after the workspace locator points to the reviewed snapshot. The agent install runbook in `AGENTS.md` handles the dormant, unconfigured case with `-AllowUnconfigured`.

New installations ask the user to choose a private folder. This teacher/development installation has already migrated its existing inputs to the chosen folder. Configuration, observed schemas, reports, and source documents stay there; browser authentication and submission state stay in a separate local runtime. Migration preserved existing form IDs, approval records, and submission history. The existing run/check and scheduled wrappers forward to the verified installed snapshot through the local locator.

Open `outputs/DemoForms.bat` for an isolated synthetic preview. Development validation uses `outputs/.venv/Scripts/python.exe -m unittest discover -s tests` and `outputs/.venv/Scripts/python.exe outputs/formfiller/web_static/ui_smoke.py`. No production responses are submitted by these tests.

Teacher installation and first-use instructions are in [docs/teacher-installation-guide.md](docs/teacher-installation-guide.md). The development scope and acceptance checks are in [docs/webui-onboarding-brief.md](docs/webui-onboarding-brief.md).

## Development isolation

From the repository root, build the clean source bundle and its Windows Sandbox definition:

```powershell
pwsh -NoProfile -File .\tools\Build-CleanSource.ps1
```

The script copies an explicit application source allowlist, `outputs/requirements.txt`, and approved static web asset types into `tools/artifacts/formfiller-clean-source`. It does not package configuration, responses, the district calendar, logs, reports, persistent state, virtual environments, browser data, or the existing tests. It creates `tools/artifacts/FormFiller-Development.wsb`, which maps only that sanitized bundle read-only and disables networking and clipboard, printer, audio, and video redirection.

Open the generated `.wsb` file yourself, then copy the bundle from `C:\FormFillerSource` into a writable folder inside the Sandbox before editing. This keeps the host checkout and private workspace outside that Sandbox session. Windows Sandbox availability depends on Windows edition and virtualization setup. The generated file describes a boundary; it does not move the current Codex session into the Sandbox or restrict local tools that already have host access. For agent work that must not have access to private inputs, run the agent inside a separate VM/account that has no private workspace mount and no authenticated browser profile. The default bundle disables networking, which suits offline inspection and testing. If the in-Sandbox agent needs its service connection, regenerate with `-AllowAgentNetwork`; that changes only the Sandbox network setting and still mounts only the clean, read-only bundle. Do not copy private files, credentials, or authenticated browser data into that environment. Use an approved offline wheelhouse for dependencies when networking remains off.

Demo and preview development must use synthetic fixtures and local mock forms. Do not point a development preview at a private config, live Forms URL, authenticated browser profile, or production service. Do not include private records in tests, screenshots, logs, or issue reports.

## Reviewed production snapshot

Build the clean source bundle from reviewed code, inspect the source changes and bundle inventory, then install it outside this checkout:

```powershell
pwsh -NoProfile -File .\tools\Install-ReviewedSnapshot.ps1 `
  -Destination 'C:\Program Files\FormFiller\snapshot-2026-10-02' -InstallDependencies
```

The installer refuses any destination inside the editable checkout and requires a new or empty install directory. It copies only the clean application source, static assets, and dependency manifest, creates a dedicated `.venv`, and writes `install-manifest.json` with SHA-256 hashes for the application source and assets. `-InstallDependencies` installs the declared dependencies into that runtime and may require access to the approved package source. `-PythonPath` can select the base Python executable; otherwise the installer uses the Python launcher. Review the manifest when approving an installation. Updates should use a new directory for each reviewed snapshot.

Keep the user's fixed answers and approved Forms configuration in the designated private synced userworkspace. Keep the authenticated browser profile, persistent state, locks, and the single authoritative submission runner on the designated local Windows machine. Do not sync browser authentication or duplicate the stateful runner across devices. Start the installed app with `Run-FormFillerPrivate.ps1`; the first-run flow asks the user to choose the private workspace. Later runs use the saved local workspace locator. Both installed launchers verify the source root, complete executable/static-asset inventory, and SHA-256 hashes before starting:

```powershell
& 'C:\Program Files\FormFiller\snapshot-2026-10-02\Run-FormFillerOperation.ps1'
& 'C:\Program Files\FormFiller\snapshot-2026-10-02\Run-FormFillerOperation.ps1' -CheckOnly
```

The first command performs the normal sanitized run; the second checks status without requesting submission. Never copy private files into the code snapshot or development bundle. This repository's current operating path instructions are in `AGENTS.md`; migration of the private workspace and wiring the installed runtime to it must be completed and reviewed before switching scheduled production use.

Development work must not submit live responses. A code change is not authorization to run the production workflow. Keep user-facing status sanitized to date, aliases, status codes, and counts. Windows Sandbox is not currently installed on this machine; the generated definition is a setup artifact, not an active restriction on this host agent.
