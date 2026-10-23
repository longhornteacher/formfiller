FormFiller environment check (version 2)
========================================

Purpose: find out what this computer's security setup allows, so FormFiller's
install can be designed to work on it.

To run: unzip this folder anywhere you can write (for example Documents), then
double-click Run-Check.bat. It takes about two to five minutes. It needs
internet access and downloads about 100 MB into a temporary folder.

It does NOT: install anything permanently, change settings, bypass any policy,
read your files, sign in to anything, or submit anything.

It DOES: look at Windows, PowerShell, Python, Edge and network settings; try
running small harmless programs and scripts (including unsigned ones and ones
marked as "downloaded from the internet") from your user folders; create a
temporary virtual environment and install FormFiller's Python dependencies
(Playwright, openpyxl, tzdata) into it; start Edge in the background through
Playwright; download, but never run, the Python installer to check its
signature; create and delete a never-run scheduled task and a temporary
Desktop shortcut; and try to reach python.org, PyPI, GitHub, Microsoft sign-in
and Forms. Everything it creates is removed.

Privacy: the log replaces your user name, computer name and domain with
placeholders. It lists Edge policy names, antivirus product names and the
certificate issuer names seen on web connections, which identify the district's
setup but no person. Read it before sharing if you like.

If double-clicking fails, or the window shows an error, that is a result too.
Send the file named Check-startup-error.txt from this folder.

Send back: the file named FormFiller-Check-<date>.log in this folder.
