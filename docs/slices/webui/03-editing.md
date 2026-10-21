# Slice 03 — Draft protection and revision conflicts

Prerequisite: slice 02 reviewed. Review finding 3.

## Problem and result

Unsaved edits disappear on navigation, a green reviewed badge persists over dirty inputs, and stale saves overwrite newer responses. Preserve the user's working draft and reject stale updates without changing existing approval semantics.

## Touchpoints

`web.py`, `store.py`, `app.js`, and existing form/Skyward editor tests. Use the slice 01 navigation entry point.

## Contract and implementation

- Return an opaque configuration revision with each editable form and Skyward settings DTO. It must cover all editable values, including form name and active/archive state. Keep it distinct from the review token, which intentionally excludes rename-only changes.
- Require the expected revision for updates. Read/compare/write under the shared mutation lock. Missing or mismatched revisions return a safe conflict, preserve stored data, and never silently fall back to last-writer-wins.
- For new Skyward settings, return an explicit initial revision/sentinel so two tabs cannot both create settings from an obsolete empty state. Update repository clients/tests together with the contract.
- Keep drafts in page memory. Implement Save/Discard/Stay for switching forms, navigation, in-app refresh, and relevant modal closing. Guard browser close/reload with the native unsaved-change mechanism. Do not store answers in browser storage or URLs.
- On validation failure or conflict, keep the draft. Offer deliberate reload/discard of the latest stored version; do not silently merge answers, approve them, or resubmit a stale payload.
- Make draft status, saved status, and review status separate. Disable review of dirty inputs. A rename/no-op save preserves answer approval and must not falsely say review is needed. Meaningful answer/schema changes require review.
- Protect Skyward settings drafts and whole-list updates using the same principles, without adding posting capability.

## Acceptance

1. Edit an answer and attempt every supported departure: Stay retains it; Discard is explicit; Save navigates only after successful save.
2. A failed save keeps inputs and stays on the editor; a conflict keeps the draft and leaves stored version B intact.
3. Two tabs load A; one saves B; the other saves A: conflict, no overwrite. Repeat for rename-only updates and Skyward settings.
4. Dirty reviewed forms show Unsaved changes and cannot imply the displayed draft is approved.
5. Save, explicit review, edit, save, and review again works; rename/no-op saves preserve existing policy approval.
6. No response values appear in browser storage, URLs, diagnostics, or exception output.

Use temporary stores and controlled synthetic browser flows. Report the revision definition and draft/navigation guard interface for slices 04–07.
