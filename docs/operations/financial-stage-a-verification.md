# UMC Financial v1 — Stage A verification, 2026-10-22

Scope: implementation-plan Tasks 01–10 (stabilization and isolated test infrastructure). This is **not** completion or activation of the financial-v1 ledger/capture/refund/payout lifecycle, and it is not a production rollout approval.

## Implemented boundaries

- Authenticated managers are authorized for the exact order/creator assignment. Operational mutations recheck the assignment under order/pair row locks and use the same SQL session for interaction/complaint writes. Capacity checks happen inside the order transaction; external notifications and referral side effects run after commit.
- Contradictory OK/NO_DEAL opens ISSUE. ISSUE is durable before complaint-description input, remains sticky across ordinary replies, cancellation/reactivation and reminder scheduling, and opens an independently reviewable legacy financial case.
- Canonical feedback prefixes determine outcomes; free-text reasons cannot turn NO_DEAL into success/postpone. Manager complaint deduplication distinguishes creators and substantive reports; exact retries preserve the stop without duplicate support notifications.
- Legacy payout creation and mark-paid share a recipient-row mutex and durable case/guard checks. PostgreSQL `FOR NO KEY UPDATE` retains exclusive financial serialization while avoiding complaint/actor foreign-key `KEY SHARE` deadlocks. Historical income, paid facts and payout reserves are not rewritten by case review.
- Financial operators use signed MiniApp identity and actual current DB-admin permission; blocked/deleted accounts cannot clear a case. Versioned, reasoned, idempotent no-adjustment review releases only its selected case. Unknown/negative/unreconciled sources stay blocked for later corrective financial commands. Raw Interaction/Payout/Income administrative edits cannot bypass this path.
- Payment receipt replay is independent of later order state or user country. Confirmation locks its order before receipt identity lookup/write. A real two-backend duplicate-capture regression no longer raises the payments-order uniqueness error.
- Feedback scheduling respects actual send failure. Referral reconciliation distinguishes the referred user; metadata uniqueness matches the existing PostgreSQL migration.
- Fresh migrations commit revisions individually, avoiding PostgreSQL enum-value use before commit. Safety-table downgrade serializes checks/drop and refuses to erase case history.

## Executed verification

The canonical existing CI selection (`not e2e`) was exercised with explicit isolated PostgreSQL required and inherited live E2E settings cleared:

```text
3890 passed, 19 skipped, 18 deselected, 104 warnings
Required coverage 98% reached: 98.07%
```

`ruff check src tests` passed. `mypy src` passed for 280 source files. Formatting and `git diff --check` passed.

The same Stage A source was built into a standalone test image. Source hashes for models, interaction/complaint services and MiniApp API were independently compared with the worktree. The isolated Compose contour then ran:

```text
86 PostgreSQL tests passed in 179.09s
```

The Compose project used only `db_test`, `migrate_test`, and `test`, an internal network, tmpfs PostgreSQL data, no host-published DB port, no bind mounts or production overlays, and `--env-file /dev/null`. Its containers/network were removed afterward. No application/bot production service was restarted.

Coverage success is separate from assertion success: earlier integration/default/fixture and concurrency-observer failures were repaired, not hidden by lowering the coverage threshold or increasing timeouts. SQLite remains only a legacy-flow fixture, never the financial locking/migration authority. Optional browser UI scenarios were not part of this canonical gate; their separate fixture compatibility remains a later UI verification item.

## Review and release boundaries

Independent reviews found and drove repairs to premature success after postpone, administrative bypass, downgrade/guard races, missing operational review, free-text outcome injection, and multi-creator complaint scope. The final machine-readable review artifact is kept with the execution evidence, not treated as a substitute for executed tests.

No live provider/bank permissions or transfer outcome were exercised. No money was transferred, no real notifications were sent, no production migrations/deployment occurred, and no new v1 tariff or payout gate was enabled. Legal terms, the selection refund-window duration, per-order selection deadlines, runtime-vs-migration DB-role separation, the complete B lifecycle, writer cutoff/replay reconciliation and the eventual controlled pilot remain required before any real new financial sale.
