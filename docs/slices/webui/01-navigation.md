# Slice 01 — Navigation and async render ownership

Status is tracked in [ACTIVE_HANDOFF.md](../../ACTIVE_HANDOFF.md). Prerequisite: baseline source and working tree inspected.

## Problem and result

A delayed Forms request can render over Teacher Guide while the breadcrumb and selected navigation still say Guide. Mutation callbacks can also force an old view back into the root. Make every asynchronous render belong to the view request that initiated it.

## Touchpoints

`outputs/formfiller/web_static/app.js`: `navigateView`, `loadView`, `loadForms`, setup rendering, and mutation refresh callbacks. Add a small local JS helper only if it reduces repetition; preserve the offline CSP and packaging rules.

## Implementation

- Introduce a view/request generation and capture the intended view before awaiting data. Check ownership before changing root content, view-specific notices, focus, or loading state.
- Apply this to every async view loader, including Forms, Setup, and Skyward; do not merely add a check to `loadView` while leaving direct render callbacks unguarded.
- Mutation completion may update cached authoritative data. Refresh the originating view only if it still owns the screen. Do not discard a pending operation merely because navigation changed.
- Obsolete GET requests may be aborted. Do not abort/retry server mutations as a navigation convenience or describe a fetch abort as cancellation of a run.
- Make loading/error UI consistent with the selected view. Do not leave an old editable page under a new breadcrumb after failure.
- Create one navigation entry point that slice 03 can extend with a dirty-state guard. Retain returning-user Forms behavior and all existing views.

## Acceptance

1. Delay `/api/forms`, navigate to Guide, release the response: Guide content, breadcrumb, and navigation stay coherent.
2. Two requests for the same view complete in reverse order: only the latest may render.
3. A delayed save or run response after navigation does not replace the destination view.
4. A view load failure shows an appropriate safe error state for that view.
5. Refresh and setup transitions follow the same ownership rules; no uncaught browser errors.

Use Playwright routes/local mocks to control response order. Run the synthetic UI smoke. Report the navigation interface and integration points for slice 03; do not implement draft prompts here.
