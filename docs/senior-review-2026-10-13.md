# WebUI and stack review — October 13, 2026

## Assessment

Keep the current architecture and visual direction. The deterministic runner, local persistent state, reviewed snapshot boundary, and synthetic development mode are appropriate for this application. The UI is a useful improvement for an already configured installation. It is not yet a complete self-service teacher product.

The next release should address truthful run outcomes, first-use authentication, and preservation of user work before adding integrations. Skyward should remain a preview. No framework migration is needed to resolve these issues.

This is a review and proposed implementation scope, not authorization to change production settings, approve calendars or schemas, install a snapshot, or submit responses.

## Evidence and limits

- Reviewed the launcher, WebApp/API, static UI, configuration store, runner, state, monitoring, calendar integration, deployment verification, Skyward adapter, and relevant tests and guides.
- All **140 existing unit/integration tests passed**. The synthetic Playwright UI smoke check passed, including its narrow-width overflow checks.
- Inspected synthetic screenshots of Forms, Setup, Readiness, Today, and the add-form dialog. A separate synthetic probe exercised delayed responses, unsuccessful run responses, concurrent edits, and rapid attendance marking.
- Probes used temporary synthetic data and mocked HTTP results. No private UI page or live submission was used. The unsuccessful-run probe verifies frontend behavior, not an actual production failure.
- The workspace resolver in this execution context returned no installed snapshot. This review therefore covers checkout behavior; it does not certify which UI version the user's desktop launcher currently opens. No installation or locator was changed.
- Synthetic diagnostics and screenshots are under the ignored `tools/artifacts/senior-review/` directory. Application code was not changed.

## Findings, in priority order

### 1. P1 — Run completion is presented as success even when the runner failed

Locations: `outputs/formfiller/web_static/app.js:263`, `outputs/formfiller/web.py:515`, `outputs/formfiller/web.py:241`.

The API returns HTTP 200 with the subprocess `exit_code`, even when that code is nonzero. The frontend ignores the result and always displays a green “Run finished” notice. A mocked HTTP-200 result with `exit_code: 2` reproduced this. The Today API also omits the sanitized per-form failure code, leaving little useful explanation of a failure.

The error handler unconditionally re-enables the run button. A mocked `run_outcome_requires_review` response reproduced an enabled button immediately after an uncertain outcome. The runner retains duplicate protection; this finding is about misleading feedback and inviting another operating attempt, not evidence of a duplicate submission.

Today uses the same disabled-button explanation for all cases, including when all forms are already submitted. That should say “Today's forms are complete,” rather than implying failed readiness checks.

**Proposed acceptance:** communicate completed, ordinary skip, blocked, failed, running, and outcome-requires-review separately. Use authoritative state and sanitized codes, not HTTP success alone. Uncertainty must not present a retry action. Failure before a state record exists must still have a useful safe explanation. Preserve all runner locks, calendar gates, and duplicate checks.

### 2. P1 — First-form setup has no dependable pre-inspection sign-in path

Locations: `outputs/formfiller/web_static/app.js:398`, `outputs/formfiller/web_static/app.js:165`, `outputs/formfiller/web.py:552`, `outputs/formfiller/runner.py:99`.

Setup tells an empty workspace to add and save a form before it can open dedicated Edge sign-in. The UI only saves a form after inspection succeeds. Inspection can require authentication, and its browser session closes when inspection fails. A teacher might finish authentication during the inspection wait, but that is an unreliable workaround rather than a designed sign-in flow.

Simply allowing an incomplete form to be saved does not fully solve this: the current runner excludes drafts from `_forms`, so its `--login` target cannot resolve an incomplete draft.

Calendar installation and live enablement also still require a separate administrator process. The onboarding brief explicitly permits the calendar-guide fallback, so missing calendar import is a declared scope limitation, not an accidental policy violation. It nevertheless means a new teacher cannot independently reach daily use.

**Proposed acceptance:** provide a deterministic, non-submitting manual sign-in action before successful inspection. It may use a validated draft URL or a separately reviewed authentication entry point; keep draft selection separate from the submission run set. Do not treat opening Edge as authentication success. Exercise an empty workspace and unauthenticated profile against local mocks. Define the administrator-to-teacher handoff for calendar review and live enablement.

### 3. P2 — Unsaved and stale edits can silently erase work

Locations: `outputs/formfiller/web_static/app.js:36`, `outputs/formfiller/web_static/app.js:71`, `outputs/formfiller/web_static/app.js:103`, `outputs/formfiller/web.py:340`.

Changing an answer and switching to another form discards the edit. Navigation and refresh have the same underlying replacement behavior. The frontend already calculates dirty state for approval, but it does not preserve or guard it. A previously reviewed form also keeps its green “Reviewed and ready” message while its displayed inputs have unsaved changes.

At the API level, saves do not include an expected saved-version token. A stale editor can overwrite newer saved answers: load version A, save version B elsewhere, then send A's answers with a rename. A direct synthetic probe confirmed that B is replaced. The shared operation lock prevents simultaneous writes; it does not prevent a sequential stale overwrite. Approval tokens correctly protect review, but do not protect saves.

**Proposed acceptance:** show “Unsaved changes” independently of saved approval. Preserve drafts or offer Save/Discard/Stay before switching forms, navigation, refresh, and closing. Add optimistic concurrency for form and Skyward settings saves; reject stale versions with a conflict response and retain the user's draft. A no-op save or rename must report review status accurately.

### 4. P2 — A late response can render the wrong view

Locations: `outputs/formfiller/web_static/app.js:34`, `outputs/formfiller/web_static/app.js:36`, `outputs/formfiller/web_static/app.js:49`.

View requests are not tied to the navigation that initiated them. Delaying `/api/forms`, selecting Teacher Guide, then releasing the forms response reproduced a Forms editor under a Teacher Guide breadcrumb and active navigation item.

This can also happen when a save or run finishes after navigation: callbacks still render into the shared root. View failures can leave the old page visible under a new breadcrumb.

**Proposed acceptance:** capture the requested view and use a navigation generation or equivalent ownership check before rendering. Ignore obsolete responses. Abort obsolete reads where useful, but never interpret aborting a browser request as cancellation of a server-side run. Only refresh an operation's originating view if it is still current. Add delayed-response browser coverage.

### 5. P2 — Rapid attendance marking loses the first change

Locations: `outputs/formfiller/web_static/app.js:293`, `outputs/formfiller/web.py:489`.

Every mark click sends a replacement of the entire roster's marks from the last rendered snapshot. Two clicks before the first response both use that snapshot. The second request replaces the first mark. Holding two synthetic browser requests and applying their emitted payloads in sequence reproduced the lost first change.

Private posting remains server-blocked, so this currently corrupts preview work rather than submitted attendance. It must be fixed before posting is considered.

**Proposed acceptance:** update one student against a roster revision, or serialize edits using an authoritative local draft. Preserve all acknowledged marks. Bind edits to date, course, and roster revision so a stale tab cannot mark a replacement roster. Changing the class picker must not label an old roster as the newly selected class. Keep posting unavailable throughout this work.

### 6. P2 — Form maintenance and removal have no complete recovery path

Locations: `outputs/formfiller/web_static/app.js:98`, `outputs/formfiller/web.py:340`, `outputs/formfiller/store.py:142`, `outputs/formfiller/store.py:204`.

The editor has no URL or re-inspection action for an existing form. The API can accept an inspection token on an update, but the UI does not expose that workflow. A schema change therefore lacks an ordinary teacher-facing repair path.

Removal archives the existing record, while duplicate-URL checks include archived records. A synthetic attempt to re-add a removed URL returned `duplicate_form_url`. Blocking a new identity protects submission history, but without Restore the user is stuck. `FormStoreError` is currently caught by the generic handler, so the duplicate cause becomes an unhelpful `request_failed` response.

**Proposed acceptance:** re-inspect an existing form while preserving its immutable ID; require renewed review for changed schema or responses. Add restore using the archived ID and its existing history. Never solve recovery by creating a new ID for a previously submitted form. Map known store errors to safe actionable messages. If a same-day configuration change cannot run, explain that separately from future readiness.

### 7. P2 — Modal errors and control labeling need accessibility work

Locations: `outputs/formfiller/web_static/index.html:35`, `outputs/formfiller/web_static/index.html:40`, `outputs/formfiller/web_static/app.js:199`, `outputs/formfiller/web_static/styles.css:123`.

Add-form errors are written to the global notice outside the modal. The synthetic error screenshot shows the explanation dimmed behind the dialog; that area is also inert while `showModal` is active. Put actionable validation inside the dialog and move focus to the relevant field.

Answer textboxes and selects rely on the fieldset legend but have no individual label association. A group legend does not supply an individual control name. The dialogs also need explicit names tied to their headings. The add-form name input omits `type="text"`, so it misses the CSS selector that styles text inputs and visibly appears as a small browser-default control.

**Proposed acceptance:** give each control an accessible name, name both dialogs, present modal-local errors, and make selected navigation programmatically apparent. Verify keyboard navigation, focus restoration, and the error path with synthetic data. Preserve visible focus and reduced-motion behavior.

## Stack and product direction

The existing safety boundaries are valuable: demo uses temporary synthetic configuration, API requests have loopback/Host/Origin/token checks and no-store responses, errors avoid arbitrary exception text, writes are atomic, editing shares the runner lock, review binds saved configuration, and private attendance posting is explicitly unavailable. The code also checks installed package inventory and hashes before private startup and runner launch.

Keep those mechanisms. In the files reviewed, there is no reason to introduce a new frontend framework, database, cloud runner, or generalized automation engine. Extract small services as the fixes land: an operation-result model, form edit/review service, attendance draft service, and UI navigation/draft controller. Avoid reworking the mature runner state machine to accommodate UI shortcuts.

The visual theme works: clear type, warm paper panels, readable controls, and a recognizable selection state. Usability is held back by repeated instructional copy and nine equal-weight navigation entries. Keep Forms, Today, and History prominent; group Setup, Readiness, Guide, and settings. Keep Attendance Preview visibly secondary. Rename Sync to a term such as “Source check” unless it actually manages synchronization; it currently validates local inputs. Do not imply that “Scheduled activity” proves a schedule has been installed or checked.

The narrow layout avoids horizontal overflow but spends substantial vertical space on navigation and stacked instruction panels. Reduce repeated help, make setup steps more compact, and bring the selected form's editor closer to the top on small windows. These are polish tasks after the functional findings.

The green overall “Checks ready” state coexists with “Sign-in not yet verified.” That is technically compatible with the runner checking authentication at execution time, but the product should say “Ready for runner checks; sign-in will be verified” to make the limitation clear. A valid non-school day should be an ordinary skip, not setup failure.

## Proposed work packages for later agent implementation

1. **Operation outcomes and navigation ownership.** Resolve findings 1 and 4. Define a structured sanitized run-result contract and deterministic browser response ordering. Cover nonzero exit, uncertainty, completion, ordinary skip, preflight failure, and delayed navigation with mocks. No live run or retry behavior.
2. **Durable editing and form recovery.** Resolve findings 3 and 6. Add draft handling, version conflicts, truthful saved/dirty/review status, re-inspection, and restoration without replacing IDs. Verify submitted and uncertain records remain terminal.
3. **First-use workflow and accessibility.** Resolve findings 2 and 7. Specify the pre-inspection sign-in action and administrator handoff first; then implement against local mock pages. Verify empty-workspace setup without approving a calendar, enabling live use, or submitting.
4. **Attendance preview correctness and UI polish.** Resolve finding 5 before any posting work. Verify rapid edits, stale roster revisions, and course changes. Then simplify navigation and repeated help. Live Skyward reading/posting verification remains a separate scope.

The existing tests establish a strong baseline but mostly cover isolated safe operations and the successful demo path. Extend them at the demonstrated boundaries rather than adding broad tests that repeat the implementation. Before a release, use the reviewed snapshot installation process and perform a separate deployment/version check; passing checkout tests does not establish that the desktop launcher's installed copy contains these changes.
