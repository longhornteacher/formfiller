# FormFiller local runtime

This folder contains application source used during development. Production use must run an installed, reviewed snapshot outside the editable checkout and pass its private workspace and local runtime explicitly to private mode.

Do not check private configuration, approved answers, browser profiles, persistent state, run reports, or logs into source control or include them in development bundles. For code changes, use synthetic test fixtures and local mock forms only; never exercise live submission from development.

Build a clean source bundle from the repository root with `tools/Build-CleanSource.ps1`. Review the generated bundle, then install it outside the repository with `tools/Install-ReviewedSnapshot.ps1`. The installer writes `install-manifest.json`; both installed launchers verify the manifest before startup. `Run-FormFillerPrivate.ps1` asks for a private workspace on first run. `Run-FormFillerOperation.ps1` performs the normal sanitized operation; pass `-CheckOnly` to check without requesting submission. Keep the one authoritative submission runtime and authenticated browser profile on the designated local Windows machine.

The checkout's operating instructions are in the repository-root `AGENTS.md`. Do not use this folder's editable source as the scheduled production runtime after the installed snapshot workflow is configured.
