# Slice 02 — Truthful run outcomes and uncertainty handling

Prerequisite: slice 01 reviewed. Review finding 1. This slice uses mocked runner processes only.

## Problem and result

HTTP success currently produces a green completion notice even when the subprocess exits nonzero. Errors re-enable Run without checking whether the outcome is uncertain. Give Today an authoritative result and eligibility explanation; never invite another operating attempt to resolve ambiguity.

## Touchpoints

`web.py`: `status`, `run_once`, readiness/result DTOs and safe error handling. `app.js`: Today rendering and Run handler. Existing runner, monitor, and state code are the authorities to inspect, not targets for broad redesign.

## Contract and implementation

- Implement the shared outcome vocabulary from the active handoff. Define the DTO before UI work. Include sanitized per-alias codes where valid, counts, date, and `can_run` with a reason.
- Completion requires consistent terminal success for the expected run set, not merely an HTTP 200 or a zero subprocess exit. Distinguish an ordinary non-school-day skip, already-complete day, preflight blocker, known failure, operation in progress, and unresolved outcome.
- Validate any derived code against an allowlist/pattern. Never return raw subprocess stdout/stderr, private paths, or exception text. Prefer structured authoritative state; narrowly adapt existing sanitized runner output only where necessary to explain a pre-state failure.
- Retain synchronous execution unless a small justified change is required. Do not introduce a queue, scheduler, retry engine, or second submission state machine.
- Preserve unresolved operation knowledge across refresh/reconnect. If the existing state/lock cannot represent a timeout or unknown pre-state outcome, use a minimal sanitized runtime-only operation record with reviewed serialization. It must fail closed across app restarts and not automatically clear because a process appears gone. Do not hold a parent runner lock while launching a child that needs that same lock.
- Do not provide a retry/clear-uncertainty control in this scope. Known completion and ordinary skips get distinct friendly copy. Unknown transport results require checking authoritative status and must remain blocked if still ambiguous.
- Apply slice 01 ownership rules so operation completion never forces navigation. Preserve all prerequisite and duplicate gates in the deterministic runner.

## Acceptance

1. Mock HTTP 200 with nonzero exit: no green success; a useful safe outcome appears.
2. Mock preflight failure with no new per-form records: safe blocker is shown.
3. Timeout, uncertain/submitting record, or ambiguous connection loss: no immediate re-enabled Run; refresh/restart remains safe.
4. Complete and non-school-day states have accurate distinct explanations and no submission retry affordance.
5. An in-flight operation prevents another request from launching a second runner; locks are never cleared to make testing pass.
6. Invalid/unknown codes and captured private-looking exception text cannot leak through API responses.

Test mock subprocess exits/timeouts, temporary state, and synthetic browser responses. Report the concrete DTO, unresolved-outcome persistence semantics, and expected behavior for an administrator resolving an ambiguity outside this scope.
