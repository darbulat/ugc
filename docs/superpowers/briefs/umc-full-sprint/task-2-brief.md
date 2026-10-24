# Task brief

Working directory: /home/bulat/.codex/worktrees/umc-full-sprint/ugc

## Global constraints

- Money uses integer minor units and explicit currency. Preserve shared recipient-row writer barriers, immutable history, ownership and caller transactions.
- Selection=50000, accompaniment=120000, management reward=60000 RUB minor units. Referral basis excludes accompaniment.
- claim deadline=due_at+14 days; objection window=first claim+72 hours; hold=success_final+14 days. Never infer success from silence of both parties or failed objection delivery.
- Grades 0/100/200/400 unique verified creators -> 10/12/15/20%; client 10%; both sides 3% after their referred user's first anniversary. Snapshot at payment with overrides.
- No historic money backfill, fabricated legal approval, simulated bank success, guessed social metrics or exposure of another manager's network.
- Work in `feature/umc-product-sprint-full` in the attached worktree. Do not alter the user's dirty primary checkout. Run `make fix` before commits; retain coverage floor 98%.
- Canonical baseline is 6505af2. Original spec, design-system attachment and all acceptance criteria remain in scope throughout staged delivery.


### Task 2: U01 existing Mini App design-system integration

**Files:** `miniapp/app.html`, `miniapp/max_app.html`, new `miniapp/design-system/`, `miniapp/umc-app.css`, `miniapp/umc-shell.js`; focused browser/UI tests. This task owns HTML/static files only while Task 1 owns profile backend files.

- [ ] Import the supplied CSS, fonts and brand assets; preserve original provenance and fix package-relative asset paths.
- [ ] Adapt actual existing screens without replacing working IDs/events/auth flows. Implement theme sync, viewport/safe area, form loading/error and existing empty states; mirror main actions using supported host capabilities with browser fallback.
- [ ] Verify Russian/English/Kazakh and currency formatting; do not force RUB copy onto non-RUB legacy flows. Record uncovered font glyphs and use a coherent fallback.
- [ ] Render screenshots and run browser regression checks. New financial/social screens remain coupled to their real APIs in Task 9; no fake balances, backend TODO buttons or premature U01 closure.


Full normative source: docs/product/UMC-developer-sprint-2026-10-22.html, including taskAmendments and qaItems.
