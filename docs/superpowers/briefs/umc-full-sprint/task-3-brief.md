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


### Task 3: R04 collaboration lifecycle and R02 notifications

**Files:** `domain/collaboration.py`, new application lifecycle port/service, SQL state/event adapters and migration `financial_collaboration_v1` after `creator_social_v1`; existing interaction/feedback handlers and scheduler integration.

- [ ] Test exact due+14d, claim+72h and success+14d boundaries, explicit agreement, actor/assignment ownership, immutable claim origin, due-date versions, reasoned dispute and failed-notification behavior.
- [ ] Implement persisted commands for assignment/start/claim/agree/dispute/expire/finalize and scheduler transitions with idempotency/version checks.
- [ ] Replace per-creator feedback cascades with durable campaign summaries while preserving payment/new-order/critical notifications. Notify the opposite party once per claim; record transport acceptance separately from read/consent.
- [ ] Exercise 30 creators with no 90-message cascade, a 71h dispute, both parties silent and failed delivery using the real ingress/factory/worker path.


Full normative source: docs/product/UMC-developer-sprint-2026-10-22.html, including taskAmendments and qaItems.
