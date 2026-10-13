# Slice 04 — Existing-form re-inspection and restoration

Prerequisite: slice 03 reviewed. Review finding 6.

## Problem and result

Teachers cannot re-inspect an existing form through the editor. Removed forms cannot be re-added because the archived identity still owns the URL. Provide deliberate repair and restore while retaining duplicate history.

## Touchpoints

`store.py`, `web.py`, `app.js`, and form/state tests. Reuse inspection tokens, revision conflicts, and dirty-state protection.

## Implementation

- Add a deliberate re-inspection action for the selected form, with safe URL editing if needed. Inspection must retain existing calendar/browser policy. It never submits or creates review approval.
- Keep inspected schema and replacement answers staged until the teacher explicitly saves. Do not map old answers to changed questions by guessing. Unchanged schema can preserve compatible responses; changed schema requires deliberate response preparation and review.
- Bind the inspection result to the URL, expiration, and edit context/revision. A stale inspection/save must not overwrite a concurrent edit.
- Preserve ID/alias on every repair. Respect existing same-day configuration binding and terminal submission records; explain when revised responses are for a future run.
- Provide a minimal archived-list and Restore workflow. Restore the same record/ID after revision and URL-collision checks. Never create a replacement ID to evade submitted or uncertain history.
- Map known `FormStoreError` cases to fixed sanitized codes and teacher actions. Keep unknown errors generic. Do not expose private config or arbitrary errors.

## Acceptance

1. Re-inspect/save an existing mock form: immutable identity and prior history remain.
2. Changed schema requires review; unsupported fields stay unresolved and cannot pass approval.
3. Expired/mismatched inspection token or stale revision is rejected without data loss.
4. Archive then restore retains identity, submission/uncertainty records, and duplicate protection.
5. Re-adding an archived URL points to restoration rather than silently making a new record or displaying only `request_failed`.
6. Restore or repair after a same-day submission cannot produce a second submission opportunity.

Keep UI surface small: selected-form repair and an archived section/dialog are sufficient. Report recovery API contracts and future-day versus current-day behavior.
