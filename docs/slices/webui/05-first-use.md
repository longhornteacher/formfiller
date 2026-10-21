# Slice 05 — Manual sign-in before first inspection

Prerequisite: slice 04 reviewed. Review finding 2.

## Problem and result

The sign-in action requires a saved form, but first-form save requires inspection that may require sign-in. Give a teacher a deterministic manual authentication path before inspection, while keeping unfinished forms out of the submission run set.

## Chosen approach

Use a private saved draft with a validated form URL and immutable ID, then an explicit dedicated-profile sign-in action for that draft. Inspection and response preparation complete it later. Do not invent a district authentication URL or accept arbitrary browser targets.

Extend the deterministic local application's login target selection to resolve a valid draft separately from the configured submission set. Do not weaken `_forms` filtering for submissions just to make login work. The complete no-submission path must be reviewable in the source diff.

## Touchpoints and implementation

- `web.py`, `store.py`, `app.js`, and the narrow login branch in `runner.py`/browser launcher as necessary. Reuse snapshot verification, ownership, dedicated profile, URL validation, and shared locking.
- Add an explicit save-draft/sign-in route through first-form setup. Empty-workspace users can reach it without successful schema capture. Use the draft's ID as the login target; do not send private URLs through command-line arguments or logs.
- Drafts are clearly labeled Not configured and are excluded from submission expectations. Readiness must identify unfinished drafts honestly and must not claim setup completion or silently enable running. Avoid accidentally treating draft presence as reviewed schema readiness.
- Start only the verified installed deterministic sign-in flow in private mode; tests mock the process or use isolated local-page adapters. Demo must not open school authentication.
- Represent launched, already open, launch failed, and still-unverified states honestly. Opening Edge or clicking a completion button never proves authentication. Preserve the current manual browser/console completion model unless a small deterministic improvement is needed.
- Present calendar and live enablement as administrator handoff steps. Explain their blockers; do not implement picker approval, timestamp refresh, or a live toggle.
- Update setup ordering and the teacher guide to describe the actual draft → manual sign-in → inspect → responses → save → review workflow. Preserve review requirements and duplicate protection.

## Acceptance

1. Empty temporary workspace can save a valid draft and launch mocked manual sign-in without captured schema.
2. The login branch resolves that draft, while the submission branch still excludes it. No submission method is reachable in the login test.
3. Invalid URL, unsupported host, missing/changed install, busy profile/runtime, or ownership failure blocks safely.
4. Manual sign-in launch does not mark authentication, schema review, calendar review, or live use complete.
5. Draft can later be inspected and configured using the same ID and slice 03 revisions.
6. Missing/changed/stale/out-of-coverage calendar still blocks inspection as required; UI provides an administrator handoff.

Validate with mocks/local pages, never a district account or live form. Report the narrowed login selection semantics and all remaining prerequisites.
