# WebUI execution slices

The active coordinator brief is [ACTIVE_HANDOFF.md](../../ACTIVE_HANDOFF.md). Read it before taking a slice. All slices inherit its safety, privacy, scope, and validation requirements.

**Deferred:** the user accepted the current stack and chose to wait for problems from real use. These slices are reference specifications, not an active implementation queue. Resume the full sequence only on a new user instruction; a reported break should receive the smallest justified fix.

## Order

| Order | Slice | Required predecessor | Review findings covered |
|---|---|---|---|
| 01 | [Navigation](01-navigation.md) | Baseline inspected | 4 |
| 02 | [Run outcomes](02-run-outcomes.md) | 01 | 1 |
| 03 | [Editing](03-editing.md) | 02 | 3 |
| 04 | [Form recovery](04-form-recovery.md) | 03 | 6 |
| 05 | [First use](05-first-use.md) | 04 | 2 |
| 06 | [Attendance](06-attendance.md) | 05 | 5 |
| 07 | [Accessibility and polish](07-accessibility-polish.md) | 06 | 7 and product wording |
| 08 | [Integration](08-integration.md) | 07 | Whole workflow |

The sequential order is intentional: most slices touch the same UI and API files. Navigation ownership is a short enabling fix before the higher-priority outcome work. Do not parallelize shared-file implementation or let separate agents invent different revision/draft/result contracts.

## Per-slice completion record

Every executor returns: the problem resolved, files changed, concrete contract changes, focused validation results, remaining limitations, and packaging impact. The coordinator examines the diff, verifies acceptance, and updates the active ledger. No commit is required to complete a slice.

Acceptance is behavior-based. Existing passing tests do not resolve a reproduced bug; add focused regression coverage at that boundary. Reuse the existing test harness and synthetic smoke script rather than building an unrelated testing system.
