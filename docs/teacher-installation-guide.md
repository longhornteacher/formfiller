# FormFiller: installation and first use

This guide is for teachers using the installed Windows application. Installation is done by an AI agent (Claude Code or Codex); everyday use does not need one.

## Install and open FormFiller

Use 64-bit Windows on an Intel or AMD computer. You do not need to install Python or PowerShell yourself: the agent prepares missing dependencies under your Windows account. First setup needs internet access. After setup, use the Launch FormFiller desktop shortcut; it opens the app without a terminal window.

1. Ask an agent (Claude Code or Codex) to install FormFiller: point it at an empty folder named FormFiller, give it the GitHub link, and say "install this".
2. On first launch, wait while setup downloads and installs missing dependencies, then choose a private folder when prompted. Existing Microsoft Edge is reused. If Edge is missing, Windows may request administrator approval to install it. If school policy blocks setup, ask IT to allow the downloads and installation; no manual commands are required in the normal setup flow.
3. Keep that folder in the location selected by your school or district. Form settings and template responses are stored there. Browser sign-in and submission tracking stay on this computer.
4. FormFiller opens in your browser and setup creates **Launch FormFiller** on your Desktop with a checklist icon. Double-click that shortcut for everyday use. Use **Setup** to continue the checklist or **Forms** to work with saved forms.

The installed application uses a reviewed local copy. The development preview is for synthetic examples and must not be used with school accounts or live form links.

## Prepare a form

1. In **Forms**, choose **Add form** and enter a name and the form URL.
2. Choose **Inspect form**. Inspection uses the dedicated local browser profile. The district calendar must pass its current check before FormFiller opens a form for inspection.
3. Enter the template responses for this form. Each form has its own saved responses. Date fields use the run date.
4. Choose **Save form**, then review the saved responses and explicitly confirm that they are correct.
5. Choose **Fill & submit** to submit that reviewed form without scheduling it. If you change an answer later, save and review it again. The last confirmed submission pre-fills the next visit, while newer saved edits are preserved.
6. Scheduling is optional. Expand **Scheduling (optional)** to add or pause automatic school-day submission. Existing scheduled forms keep their schedules.

Unsupported question types need attention in the form or its configuration. FormFiller does not guess an answer for an unsupported field or skip its schema checks.

## Calendar and school sign-in

FormFiller only runs on dates covered as instructional by an approved, fresh district calendar. Missing, changed, stale, or out-of-coverage calendars stop work before a form opens. A weekday alone does not make a date an instructional day.

The current setup screen can explain calendar blockers, but it does not approve or refresh a calendar. If it says the calendar needs review, ask the person who manages your FormFiller installation to complete the district calendar review through the approved process. Do not change calendar files or approval dates yourself.

School sign-in is manual in the dedicated Microsoft Edge profile. Opening the sign-in flow does not prove that sign-in succeeded; readiness remains unverified until the local runner checks it while opening a form.

## Daily use

Open **Today** to see the current date and local run status. FormFiller checks the approved calendar, the saved answers and their review state, the form fields, and prior submissions before it acts. Duplicate protection and submission tracking are handled by the local runner.

Use the explicit **Run today's forms** action only when you intend to run the reviewed forms. Setup and form review do not submit responses. An ordinary non-school-day result means there is nothing to submit that day.

**Attendance** is a preview unless the application says otherwise. A `J` in a neighboring period suggests an absence. Review every mark; the suggestion does not replace your review. Sending attendance is unavailable while posting has not been verified.

## Troubleshooting

- **Choose a private folder:** choose an empty folder intended for FormFiller data. Existing folders or runtime state need a reviewed migration.
- **Calendar needs review:** ask your FormFiller administrator to review the district source. Do not approve a calendar just to continue.
- **Saved answers need review:** open the form, check each template response, save edits, and explicitly review the saved version.
- **Sign-in not yet verified:** sign in manually in the dedicated Edge window, then let the local runner check access when it opens the form.
- **A form changed or has unsupported fields:** have the form reviewed before using its saved template responses.
- **A run is uncertain or reports a failure:** stop and review its local status before trying again. Do not submit a second time to resolve an uncertain result.

Status details use safe diagnostic codes. Contact the person who maintains your installation with the code and date; do not send private form URLs, student information, saved answers, or browser profile data.
