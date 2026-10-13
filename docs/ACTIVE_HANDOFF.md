# Active handoff: WebUI reliability and teacher workflow

Status: **Ready for implementation in the next session. No slice implemented.**

Prepared October 13, 2026. Baseline reviewed commit: `ffa40b7` (`Build teacher onboarding web UI`). Confirm current HEAD and working-tree changes before starting; this is a baseline reference, not a reset instruction.

## Mission and scope

Make the existing local WebUI trustworthy during failure, navigation, editing, first use, and recovery. Preserve the deterministic runner, immutable form identities, local state, installed-snapshot verification, and Old Schoolhouse theme. Keep Skyward attendance a preview.

The user requested this active handoff and execution slices after the senior review. This session prepares the work; it does not implement it or launch another chat. The kickoff prompt below is the instruction to use when starting implementation in a new session.

Scope is local source development with temporary synthetic fixtures and local mock pages. It includes the eight slices below. Calendar import/approval, live enablement UI, live Skyward verification/posting, new attendance rules, scheduling, production installation, and production submissions remain outside this work.

## Read first

1. Repository `AGENTS.md` and the user's senior-developer instructions in the new session.
2. This file and [execution slices](slices/webui/README.md).
3. [Senior review](senior-review-2026-10-13.md), which contains reproduced findings and evidence limits.
4. [Original onboarding brief](webui-onboarding-brief.md) and [teacher guide](teacher-installation-guide.md) for existing product intent.

This handoff is the active sequencing and implementation specification for the review fixes. The review remains historical evidence. The original brief remains the visual/safety baseline; do not redo its already implemented features or interpret its broader calendar workflow as scope for this pass. Higher-priority instructions and `AGENTS.md` still govern.

## Starting state

- Previous validation: 140 existing tests passed; synthetic UI smoke passed. These are historical results, not a substitute for testing changed code.
- Confirmed probes: nonzero runner exit shown as success; uncertainty re-enables Run; form switching discards edits; stale save overwrites newer answers; delayed Forms response overwrites Guide; rapid attendance edits lose earlier marks; archived URL cannot be re-added; modal errors appear outside the modal.
- Review was checkout-only. The workspace resolver returned no installed snapshot in that execution context. Do not infer that no installation exists, and do not create a new runtime to resolve that uncertainty.
- At handoff creation, `docs/senior-review-2026-10-13.md` and `docs/webui-onboarding-brief.md` were already untracked. The user subsequently requested a documentation commit including those supporting briefs and these handoff files. Preserve any subsequent user changes.
- Ignored synthetic probes/screenshots may exist under `tools/artifacts/senior-review/`. They are diagnostic aids, not required dependencies or approved release fixtures. Do not stage them.

## Non-negotiable boundaries

- Use source, synthetic configuration, and local mocks only. Do not open private UI pages through agent browsers or inspect private answers, student records, authentication, or live form pages for development.
- Do not invoke operational run wrappers against the user's workspace as a test. Existing isolated wrapper tests with temporary synthetic state and mocked browser/runner behavior remain allowed. Do not submit live responses, retry uncertain operations, use `--resume`, delete production locks/state, change production answers/settings, refresh production approval timestamps, approve production schemas/calendars, or rebind a runtime owner.
- Preserve loopback/Host/Origin/token checks, CSP/no-store headers, safe error codes, atomic writes, shared runner locking, schema/configuration review binding, and installed-snapshot checks.
- Authentication, locks, operation records, and submission state remain in the designated local runtime, outside synced configuration. A reviewed operation record must not become a second submission authority.
- Preserve immutable IDs and submitted/submitting/uncertain state. Restoration or re-inspection must never create a fresh identity to circumvent history.
- Browser sign-in remains manual in the dedicated local Edge profile. Opening Edge never verifies authentication. Backend browser work stays deterministic.
- Keep private attendance posting blocked in the API and UI. No external messages, telemetry, remote assets, or new scheduler behavior.
- A host checkout is not enforced isolation. For an agent that must have no private access, use the existing clean-bundle process in a separate VM/account without private mounts or credentials. A Sandbox definition alone does not isolate the current session.

## Execution model

The senior coordinator owns the shared contracts, sequencing, review, and progress ledger. Once the new session is instructed to implement, delegate one bounded slice at a time to an implementation agent using the user's selected execution model. Do not start overlapping edits in `web.py` or `app.js`. A single executor may complete the slices sequentially if delegation is unavailable.

Before each slice, inspect the current source and preceding slice's contract. Implement only that slice and its necessary focused tests; use small helper modules where they clarify responsibility. No framework, database, cloud runner, or broad refactor.

Before marking a slice complete, the coordinator reviews the actual diff and acceptance evidence. Update the ledger and continuation record below. Do not require fresh user approval for routine implementation decisions within the kickoff scope. Ask only for a material scope change, a policy conflict, or genuinely missing information; continue independent authorized work.

If a slice is interrupted, leave a precise continuation record. Do not label untested work complete. Do not skip a required slice merely because existing tests pass.

## Shared contracts

These are minimum semantics. Name small internal helpers to fit the codebase; record the concrete contract in the relevant slice before dependent work starts.

**Navigation:** each requested view and read has an identity/generation. Only its current owner may replace that view's DOM or notices. Cancelling a UI read does not cancel a server-side run. Mutation results can update authoritative cached data without forcing the user back to the originating view.

**Run outcome:** expose a structured, sanitized outcome separate from HTTP transport success: `completed`, `skipped`, `blocked`, `failed`, `running`, or `requires_review`. Provide date, safe code(s), alias/count summaries, and authoritative run eligibility/reason. Nonzero exit never implies completion. Unknown/ambiguous results fail closed. Do not expose subprocess output or arbitrary exception text.

**Revision versus approval:** a configuration revision detects stale saves and includes all user-editable fields, including name and archive state. A review token continues to bind the submission policy as it does today; rename alone must not require new answer review. Compare expected revision under the shared mutation lock. Missing/stale revisions for updates must not silently overwrite data. Update every repository client and fixture that uses a changed API contract.

**Draft privacy:** hold unsaved responses in page memory. Do not put them in URLs, localStorage, sessionStorage, browser history state, console logs, or fixtures. Use explicit Save/Discard/Stay transitions; page close/reload can use the browser's native unsaved-change prompt. Saved private draft records, where needed for onboarding, use the existing private store and remain outside the submission set until configured and reviewed.

**Attendance:** marks belong to a date, course, and roster generation. Mutations must not overwrite a different or replacement roster. The canonical server model separates the loaded course from the class selected for the next load. Existing J suggestion semantics do not change.

## Ordered slices and progress

Execute in this order. Each slice assumes prior slices are reviewed and accepted in the working tree.

| Slice | Deliverable | Status | Evidence/commit |
|---|---|---|---|
| [01](slices/webui/01-navigation.md) | Navigation and async render ownership | Pending | — |
| [02](slices/webui/02-run-outcomes.md) | Truthful run outcomes and uncertainty handling | Pending | — |
| [03](slices/webui/03-editing.md) | Draft protection and revision conflicts | Pending | — |
| [04](slices/webui/04-form-recovery.md) | Existing-form re-inspection and restoration | Pending | — |
| [05](slices/webui/05-first-use.md) | Manual sign-in before first inspection | Pending | — |
| [06](slices/webui/06-attendance.md) | Reliable attendance preview mutations | Pending | — |
| [07](slices/webui/07-accessibility-polish.md) | Accessible errors and coherent UI wording | Pending | — |
| [08](slices/webui/08-integration.md) | Integrated verification and release handoff | Pending | — |

Status vocabulary: Pending, In progress, Needs review, Complete. Record a blocker in the continuation record rather than claiming completion. Commit hashes are optional if no commit has been requested.

## Validation and delivery

Use the actual checkout location. From repository root, the existing Windows development commands are:

```powershell
& './outputs/.venv/Scripts/python.exe' -m unittest discover -s tests
& './outputs/.venv/Scripts/python.exe' outputs/formfiller/web_static/ui_smoke.py
```

Focused tests should use temporary directories, mocks, and local pages. Inspect synthetic UI states at desktop and narrow widths, keyboard-only, and actual browser zoom where available. Reducing the viewport is useful reflow coverage but is not by itself proof of 200% browser zoom behavior.

When source changes create new runtime helpers, include them in the explicit clean-source packaging allowlist and its tests. Check deployment inventory/static assets with temporary installation fixtures only. Do not install or switch the user's production snapshot during this work.

The implementation kickoff does not request a commit or push. If the user separately requests a commit, enable the hook and audit the exact staged contents from repository root:

```powershell
git config core.hooksPath .githooks
& './outputs/.venv/Scripts/python.exe' -m tools.audit_privacy --staged
```

Review fixtures manually for real names; pattern auditing cannot establish that. Do not stage ignored diagnostic artifacts or unrelated user work.

## Continuation record — update after every slice

- Current slice: None; start 01.
- Last completed slice: None.
- Changed application files: None at handoff creation.
- Agreed concrete API contracts: Minimum semantics above; record implementation details as slices land.
- Latest validation: Historical 140-test baseline and synthetic smoke pass from the review.
- Unresolved issues: Installed version not verified; live integration remains out of scope.
- Next action: Inspect current git status/source, then implement slice 01.
- Release state: Development planning only; no production installation or submissions.

## New-session kickoff prompt

Copy this into the new session opened on this repository:

> Read AGENTS.md, docs/ACTIVE_HANDOFF.md, and docs/slices/webui/README.md. Implement the WebUI reliability and teacher-workflow work through slices 01–08 in order. Act as senior coordinator and delegate each bounded coding slice to an implementation agent where available; review its diff and acceptance evidence before advancing. Preserve existing user changes. Use synthetic data and local mocks only; isolated test approvals/settings are allowed. Do not run production forms, change production approvals/settings, enable private attendance posting, install or switch a production snapshot, create a schedule, commit, or push. Update the active handoff ledger and continuation record after each slice. Continue through the defined scope without stopping for routine implementation decisions, and finish with validated source changes and a concise release handoff.
