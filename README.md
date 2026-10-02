# FormFiller

FormFiller separates application code from the user's private form workspace. The editable checkout is for development; the daily runner must use a reviewed installed snapshot and its designated private workspace.

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

Double-click `LaunchWebUI.bat` in the repository root to start the WebUI and open it in your default browser. It uses the existing installed app when configured. On first use it installs the app runtime, then asks you to choose a private workspace. Python 3.11+ and PowerShell 7 are required. Keep the launcher window open while using the UI. `outputs/OpenForms.bat` also forwards to this launcher.

If Codex's packaged Windows app created the original installation in its redirected app-data folder, the desktop launcher discovers that existing locator and preserves the same private workspace and local submission state. It does not create a second runtime or reset approvals. A new installation shows progress while creating Python and installing dependencies.

Forms is the default view: select a form, edit its saved answers, add a form, or remove one. Changed answers require an explicit review before a run. Today, History, Sync, and Readiness are secondary navigation views. Sync checks local source validity; the selected folder's sync provider handles file transfer. FormFiller does not refresh calendar approval dates during a sync check.

New installations ask the user to choose a private folder. This teacher/development installation has already migrated its existing inputs to the chosen folder. Configuration, observed schemas, reports, and source documents stay there; browser authentication and submission state stay in a separate local runtime. Migration preserved existing form IDs, approval records, and submission history. The existing run/check and scheduled wrappers forward to the verified installed snapshot through the local locator.

Open `outputs/DemoForms.bat` for an isolated synthetic preview. Development validation uses `outputs/.venv/Scripts/python.exe -m unittest discover -s tests` and `outputs/.venv/Scripts/python.exe outputs/formfiller/web_static/ui_smoke.py`. No production responses are submitted by these tests.

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
