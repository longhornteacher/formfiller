# Slice 07 — Accessible errors and coherent UI wording

Prerequisite: slice 06 reviewed. Review finding 7 and product-direction notes. Do not change backend safety policies in this slice.

## Implementation

- Put add/edit/recovery dialog errors inside the active dialog. Link errors to fields, move focus deliberately, and restore focus on close. Use fixed safe messages for known codes and generic fallback for unknown codes.
- Give answer textboxes/selects individual accessible names; keep group labels for multi-choice/matrix controls. Name dialogs through their headings. Add `type="text"` to the add-form name input or equivalent consistent styling.
- Make current navigation and selected form apparent programmatically. Preserve visible focus, reduced motion, and keyboard access to all dialogs and new recovery actions.
- Keep Forms, Today, and History prominent. Group setup/help/settings destinations and make Attendance Preview secondary. Keep all views reachable; do not redesign routing or add a framework.
- Rename Sync to Source check in teacher-facing copy while retaining compatible backend route names if appropriate. Explain that the folder provider transfers files and the app checks local validity.
- Remove repeated template instructions while retaining concise persistent help. Compress setup cards and narrow-window navigation; keep important blockers and editor actions easy to reach.
- Make overall readiness wording compatible with unverified sign-in. Treat a valid non-school day as an ordinary skip, not incomplete calendar setup.
- Remove wording that implies a scheduler was installed or checked when no schedule status is available. Do not add a schedule to make the wording true.

## Acceptance

1. Invalid add-form input has a visible modal-local error and a meaningful focus destination.
2. Keyboard-only create/edit/review/re-inspect/archive/restore/sign-in entry and draft prompts work with sensible focus restoration.
3. Accessibility inspection identifies names for individual answer controls and dialogs, and the current navigation state.
4. Desktop and narrow screenshots show readable Forms, Today outcomes, setup blockers, recovery dialogs, and Attendance Preview without horizontal overflow.
5. Check 200% zoom using actual browser zoom when available; document the method and any limit. A smaller viewport alone is only reflow testing.
6. Source check, readiness, draft/review, and preview wording matches server capabilities. No remote assets, private screenshots, or new telemetry.

Use synthetic views only. Keep CSS/theme changes restrained. Report screenshots' ignored local paths and any accessibility limitation requiring follow-up.
