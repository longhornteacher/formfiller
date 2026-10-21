# Slice 06 — Reliable attendance preview mutations

Prerequisite: slice 05 reviewed. Review finding 5. Posting remains unavailable in private mode.

## Problem and result

Rapid clicks send full marks snapshots from the same old render; the second overwrites the first. A class picker may display a new selection above an old roster. Make edits refer to the exact loaded roster and preserve acknowledged marks.

## Chosen contract and implementation

- Return a roster generation with the server's date and loaded course. Create a new generation on load/reload, date rollover, or invalidation after relevant settings changes.
- Change marks mutations to a single-student update bound to expected date, course, and roster generation. Under the shared mutation lock, reject stale/unknown roster, invalid student, and unsupported mark.
- Serialize the page's outstanding mark edits or use an explicit pending edit queue so each change is acknowledged before its response is applied. Do not let an old full-state response erase newer local pending edits. Reuse slice 01 render ownership.
- Maintain loaded course separately from the next class selected. Label the visible roster with its loaded course. Changing selection neither relabels old students nor submits edits for the new course. Clear or visibly invalidate old roster on configuration changes.
- If reload/navigation would replace a roster while edits are pending, finish or deliberately cancel unsent local edits. Never replay stale marks onto a new roster. All requests remain bound to their original context.
- Retain existing J suggestions and explicit teacher review. Names/details remain memory-only with no diagnostic persistence.
- Keep `/api/attendance/submit` server-blocked in private mode; no live verification, attendance posting, or new suggestion policy.

## Acceptance

1. Two rapid edits to different students both survive slow controlled responses.
2. Multiple rapid edits to the same student preserve the final intended mark.
3. A stale tab after reload/date rollover/course change receives a conflict; the replacement roster is unchanged.
4. Selecting another class does not label or edit the old roster as that class.
5. Settings change invalidates affected roster; pending/failed edits have truthful UI state.
6. Direct private submit requests remain blocked even with valid staged marks.

Use synthetic rosters and controlled request order. Report the mark API and roster invalidation rules; update demo smoke callers to the contract.
