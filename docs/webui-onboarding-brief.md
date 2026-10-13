# Implementation brief: Teacher onboarding and Old Schoolhouse WebUI

## Objective

Make FormFiller understandable and usable by a new teacher without an AI agent. Guide the teacher from opening the installed application to preparing reviewed Forms responses, and explain every remaining requirement before live use. Give the interface the warm, orderly feel of an old schoolhouse.

This brief authorizes development with synthetic data and local mock forms. It does not authorize live submissions, production configuration changes, or approval of calendars or schemas on the user's behalf.

## Visual direction: Old Schoolhouse

Use cream notebook paper, chalkboard green, dark walnut accents, muted brick red, and restrained brass details. Suggested starting tokens: paper #FFF8E7, ink #26352B, chalkboard #23483D, walnut #654632, brick #9C4036, brass #AE873B. Verify contrast before finalizing combinations.

Use a locally available serif such as Georgia for headings and a readable system sans-serif for controls and body copy. Give the sidebar the character of a chalkboard, with paper-like content panels and subtle ruled lines in decorative areas. Keep form fields plain, generously spaced, and easy to read. Use simple schoolhouse motifs sparingly: a bell, notebook, or pencil. Status must always include text, not just a color or icon.

Replace the current meadow background, pixel frames, monospace body text, and game-like shadows. Preserve recognizable navigation and clear button hierarchy. Build the theme in CSS using local assets only; retain the existing content security policy and offline behavior. Avoid remote fonts, decorative animation, and texture behind important text. Support keyboard navigation, visible focus, reduced motion, narrow windows, and 200% zoom.

## Required experience

### 1. A resumable setup checklist

Show a welcome checklist on first use, and make it available later through “Setup.” Returning configured users should still land on Forms. Derive checklist completion from actual configuration and readiness checks; completing a visual step must never create approval or enable live operation.

Steps:

1. **Choose your private folder.** Reuse the existing folder chooser. Explain that settings and saved responses go here, while sign-in and submission tracking stay on this computer. Do not show internal paths unnecessarily.
2. **Set up your school calendar.** Provide a source file picker, validation summary, coverage dates, instructional-day count, and a separate explicit review action. Explain unsupported files and missing, changed, or stale sources in plain language. Only offer approval through a reviewed implementation of the existing calendar policy; never mark a source approved merely because it was selected. If that workflow cannot fit the initial release, show an actionable setup guide and keep this step blocked.
3. **Sign in to your school account.** Open the dedicated Edge sign-in flow through the deterministic local application. Explain that the teacher signs in manually and then returns to FormFiller. Opening a browser is not proof of successful authentication; represent unverified status honestly.
4. **Add your first form.** Reuse the existing URL inspection and answer editor. Explain any prerequisite that prevents inspection, including the calendar gate.
5. **Review readiness.** Show what is ready, what needs attention, and what a future run will do. Live use requires a separate explicit action through the existing reviewed configuration policy. Setup completion must not submit anything.

Allow teachers to leave setup and resume later without losing saved work. Do not ask them to edit JSON files in the primary flow.

### 2. Actionable readiness messages

Map known sanitized codes to teacher-facing explanations and concrete next actions. Examples: “Your school calendar needs review,” “These saved answers have changed; review them before use,” and “Sign-in is checked when the runner opens the form.” Keep diagnostic codes in an optional details area.

Differentiate ready, needs attention, not yet verified, and an ordinary non-school-day skip. Unknown codes must receive a safe generic explanation, never raw exception text. Buttons should take teachers to the relevant setup step or editor. Retain all existing fail-closed checks.

### 3. Explain template responses inside Forms

Keep the existing flow: name and URL → inspect questions → enter answers → save → explicitly review.

Call saved answers “Template responses” in teacher-facing explanations. State: “These answers are reused each time this form runs. Date fields use the run date.” Show a short first-use walkthrough and persistent help near the editor. Use a clear primary action at each stage.

Distinguish “Saved — review needed” from “Reviewed and ready.” Editing answers invalidates review as it does today. Explain unsupported question types without guessing answers or allowing submission past schema validation. Avoid implying that templates are shared across forms; each form has its own saved responses.

### 4. A useful setup completion screen

Show configured form count, reviewed form count, calendar coverage, and any unresolved requirements. Explain that submissions occur only on approved instructional dates and that the runner tracks duplicates. Use “Return to Forms” as the completion action. If a run action is available, make its purpose explicit and keep it separate from completing setup. Never silently create a schedule.

### 5. Honest Skyward preview and friendly configuration

Label Attendance as “Preview” until live reading and posting have been verified. Disable “Send attendance” visibly in private mode while posting is unavailable, with a nearby explanation. Enforce that restriction on the server as well.

Add a Skyward settings screen with district login URL, class name, class identifier, and optional period. Validate inputs with the existing configuration rules, save only in the private workspace, and offer add/edit/remove class controls. Provide illustrated synthetic instructions for locating the class identifier; do not pretend teachers can derive it from the login URL alone. Keep sign-in manual in the dedicated Edge profile.

Explain the current attendance suggestion: a J in a neighboring period suggests an absence, and the teacher must review every mark. Do not introduce configurable habits, new attendance rules, or unattended posting in this release. Other Skyward inputs and habits require a separate specification after the integration is verified.

### 6. A short teacher guide

Add an in-app quick-start guide and a concise installation guide covering prerequisites, launch, setup, template responses, readiness, daily use, and troubleshooting. Be explicit that no AI account or agent is needed. Use fictional examples and synthetic screenshots only. Separate installation requirements from everyday usage.

## Implementation boundaries

Primary touchpoints are `outputs/formfiller/web_static/index.html`, `app.js`, `styles.css`, and `outputs/formfiller/web.py`. Reuse workspace selection, form inspection, review tokens, configuration validation, and the dedicated browser flow. Add server endpoints only where required; validate every mutation and retain existing locking, ownership, CSRF, loopback access, and installation verification protections.

The calendar picker/review flow and a UI action to enable live operation need backend design against the existing policy before coding. Do not implement them as direct JSON edits or timestamp updates. Where new workflow support is deferred, the UI must explain the remaining step accurately rather than mark it complete.

Private UI data must never enter AI tools, telemetry, external assets, screenshots, fixtures, or development logs. Agent inspection uses the synthetic demo only. Keep authentication, locks, and submission state outside synced configuration. An updated development UI must be reviewed and installed as a new snapshot before production use.

## Delivery order

1. Old Schoolhouse CSS theme, plain-language readiness, template guidance, honest Skyward preview, and teacher guide.
2. Resumable setup checklist and manual sign-in entry point using existing services.
3. Skyward configuration editor and reviewed calendar onboarding workflow. Add live enablement UI only after its explicit-review semantics are agreed and tested.

Each increment should be independently reviewable. Report unfinished capabilities honestly in the guide and UI.

## Acceptance and validation

- A teacher can add a mock form, save responses, review them, edit them, and see that review is required again without opening configuration files.
- Fresh setup and returning-user flows work; partial setup survives restart and never claims readiness from UI state alone.
- Missing, changed, stale, and out-of-coverage calendars remain blocked, including before form inspection opens Edge. Setup does not weaken the current calendar gate.
- Opening sign-in does not falsely mark authentication verified. Completing setup neither submits forms nor enables live operation automatically.
- Skyward settings reject invalid input and persist only to a synthetic private workspace in tests. Private-mode posting remains blocked even if an API request is made directly.
- Known blockers have useful next actions; unknown errors do not reveal private data or exception text.
- Visually inspect all views, dialogs, empty states, errors, and setup screens using the synthetic demo at desktop and narrow widths, with keyboard navigation and 200% zoom.
- Run existing unit tests and UI smoke checks. Add focused tests for new configuration mutations, approval behavior, and setup status derivation; avoid tests that merely repeat markup.
- Before committing, audit the exact staged files with the required privacy audit and manually review fixtures and screenshots for real names. Do not run production submissions as a validation step.
