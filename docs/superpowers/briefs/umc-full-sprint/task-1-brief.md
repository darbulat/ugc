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


### Task 1: D01 / D02 canonical profiles and social accounts

**Files:** new `domain/social.py`, `application/social_ports.py`, `application/services/social_account_service.py`, SQL/memory adapters; extend profile ports/adapters and Instagram verification as needed. New migration `creator_social_v1` follows `management_reward_std`. New social/identity service and PostgreSQL tests.

**Interfaces:** one creator/user owns multiple social accounts. A verified Instagram is required to add other networks; those links remain unverified. Persist platform/url/handle, known metric/source/time and work format; unknown metrics stay NULL. Expose `SocialAccountService.list_accounts`, `save_account`, `remove_account`, `next_platform` through a typed port. These backend methods are integrated into API/UI in Task 9, so backend completion alone does not close D01/D02.

- [ ] Write and observe failing tests for ownership, required IG verification, valid platform URLs, ordered prompts, absence of invented metrics, stable identity uniqueness and old profiles.
- [ ] Implement DTOs, service, SQL/memory adapters and non-destructive migration with duplicate preflight.
- [ ] Verify service behavior and actual PostgreSQL constraints/races; review the scoped diff.
- [ ] Integrate registration/profile API and UI in Task 9 before closing D01/D02.


Full normative source: docs/product/UMC-developer-sprint-2026-10-22.html, including taskAmendments and qaItems.
