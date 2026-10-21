# Slice 08 — Integrated verification and release handoff

Prerequisite: slices 01–07 reviewed. This slice completes development delivery; it does not deploy.

## Integration work

- Review the combined diff and API callers for consistency. Resolve narrow integration failures; do not open a new feature scope.
- Cover an integrated synthetic journey: empty setup → draft → mocked manual sign-in → inspection → response save → explicit review → edit/conflict → repair → archive/restore → mocked run result. Verify immutable identity throughout.
- Cover failure paths: obsolete navigation response, rejected stale save, changed schema, uncertain operation after refresh/restart, missing/stale calendar, and stale attendance roster. Confirm no shortcut enables operation past the runner's policy.
- Include any new Python helpers/local static files in the explicit clean-source package allowlist. Verify clean-source/deployment tests with temporary synthetic installation fixtures, including missing or modified code/assets. Do not call installation tooling against the user's locator/runtime.
- Confirm all runtime-only operation/draft metadata remains outside source bundles and synced config as specified. Ensure testing adapters cannot route production Forms URLs to agent-controlled browser sessions.
- Update teacher documentation to reflect delivered behavior and remaining administrator/live-integration requirements. Update the ledger to Complete only for verified slices.

## Final checks

Run the full test suite and synthetic UI smoke using the commands in ACTIVE_HANDOFF.md. Once appropriate checks pass, repeat only when a new change, failure, or unresolved concern justifies it. Inspect synthetic desktop/narrow/zoom and error states. Review fixtures manually for real names.

No commit/push is requested by the kickoff prompt. Leave a cleanly explained working-tree diff. If the user separately requests a commit, audit the exact staged contents and use the required hook before committing; never stage ignored diagnostics or unrelated user files.

## Required release handoff

Write `docs/webui-reliability-delivery.md` with:

1. Completed slices and concrete behavior changes.
2. Shared API contracts and migration implications, including old installed snapshot compatibility.
3. Test results, mock/synthetic boundaries, visual/accessibility verification method, and any unresolved limitations.
4. New package files and proof that clean-source/deployment checks passed.
5. Explicit release state: source validated, production installation/version not verified or changed, no live submissions or Skyward posting verification.
6. Separate next step for a human-reviewed new snapshot installation and installed-version verification. Do not execute it as part of this slice.

Final user response should state the achieved behavior, checks, remaining limitations, and the delivery-document link. Update ACTIVE_HANDOFF.md with final continuation state; do not erase the historical baseline or evidence limits.
