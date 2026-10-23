# Financial capture / guarded journal integration — verification

## Status and scope

Verified implementation checkpoint, **not production approval and not completion of the 52-task Financial v1 plan**. Stacked on `feat/umc-financial-v1-foundation` (foundation commit `bc12940cfc10b507781bb2836b423e1ff69e0233`). The tested source/test snapshot is Git tree `c3720ec4e73c2b46b856acf31fbfbc53bc6657be`; this document was added afterward without changing runtime, tests or configuration.

Included:

- Task 16 trusted capture path: persisted invoice/account identity, caller-owned atomic capture/allocation/item timestamps and durable basis requests. Existing invoice capture is distinct from permission to issue new sales.
- Partial Tasks 19–21: obligation issuance, internal non-bank transfers, independent authoritative obligation/journal/projection reconciliation and fail-closed readiness. These are ledger primitives, not completed cancellation/refund/payout writers or production consumer wiring.
- Immutable database-generated journal append order (`journal_append_order`, after `financial_ledger`), allocated behind the wallet writer barrier. No inferred historical timestamp/UUID backfill.
- Partial Task 25 containment: legacy SQL and memory outbox lifecycle operations exclude the entire `financial.*` namespace. This is not an implemented typed financial router, durable inbox or working financial consumer.

Task 17 assignment work and the unwired Task 22 grade prototype are **not included**. Task 17 natural pre-capture authorization and full financial manager-return integration remain open.

## Additional authorized integrity cycle

After two previous journal fix cycles, an additional conditional integrity defect was escalated and the owner explicitly authorized a further TDD cycle. A legal privileged repository append could introduce duplicate issuance with matching projections; algebraic replay alone did not establish the immutable entitlement ceiling. No ordinary public duplicate-ingress path or external payout exploit was established.

Before production edits, the existing eager-rejection regression failed `DID NOT RAISE`. A new real-PostgreSQL regression then committed `available=10000` against an independently read immutable obligation amount of `5000`, using separate distinct-key transfer attempts. The parent inspected this saved RED execution log; this is not a claim that the parent independently reran old runtime after the fix.

The minimal fix reuses `FinancialReconciliationService.require_ready` for **new** transfers after existing scope/retry checks and before append/projection. Wallet/item writer locks remain held and all reads/writes use the caller transaction. The gate checks independent persisted obligation bases, causal journal order and actual projection across the recipient/currency wallet. It does not commit, repair monetary history, change entitlement policy or authorize bank operations.

Identical saved-operation retries intentionally return the original movement without fresh writes even if later wallet corruption exists. Conflicting economic/audit payloads still raise `PayloadConflict`. Ledger consistency is not legal approval, liquidity or actor authorization.

New durable regressions cover the entitlement ceiling with repeated distinct keys, matching-projection corruption on another obligation (duplicate/missing/wrong issuance), recipient isolation and valid controls, read-only retries/conflicts, actual caller rollback, and verified lock serialization using independent backend PIDs plus `pg_blocking_pids`.

## Final local evidence

On the frozen source/test snapshot:

| Gate | Observed result |
| --- | --- |
| Parent repeated focused matrix | **95 passed**, 128.83 seconds |
| Ruff, `src tests` | Clean |
| Format check, `src tests` | **536 files** already formatted |
| Mypy, `src` | **299 source files** clean |
| Full non-e2e suite | **4329 passed, 19 skipped, 18 deselected**, 105 warnings; 714.32 seconds |
| Coverage | **23342 / 23806 executable lines = 98.05091153490717%**, unchanged floor **98%** |
| Full JUnit | **4348 cases**, zero failures/errors, 19 skipped |
| Required PostgreSQL checks | **280 passing cases** in `postgres_financial` modules; all required modules and all **9 exact transfer selectors** passed |
| Source integrity | Source/tests/config unchanged against the tested tree; no untracked source/test additions |

The parent independently parsed coverage XML and JUnit and checked `covered * 100 >= executable * 98`, rather than trusting rounded console output or pytest exit alone. The full wrapper and pytest both exited 0. Thresholds, exclusions and coverage configuration were not weakened.

The previous frozen integration run (**4262 passed / 97.87%**) failed acceptance and was not waived. Additional substantive defensive tests and the authorized fix preceded this new complete run. The earlier pytest-exit-0/coverage-failure discrepancy remains unattributed; the fail-closed report checker protects acceptance but does not claim to fix that separate tooling anomaly.

## Independent review

Separate read-only reviews approved the journal ordering/integrity and reserved namespace containment deltas. A fresh independent review of the additional authorized transfer guard against pre-fix tree `630111822939e8ac4cd095e3d500d6b9ebc66c6e` found **no scoped P1/P2 security or logic blockers** and no suggestions. It inspected the complete new PostgreSQL test file, independent basis/projection reads, lock/transaction implementation and retry semantics. This was static review, not independent reviewer execution of PostgreSQL tests or approval of the entire financial plan.

Runtime evidence above comes from the parent's actual repeated commands and separately verified gate artifacts, not from interpreting reviewer approval as execution.

## Standalone Docker / PostGIS gate

Only `docker-compose.financial-test.yml` was used. The unique owned project was `ugc-financial-integration-bafca292e988`, with an internal network, no published ports, no host bind mounts and no production env-file. Shared deployed `.env` and inherited E2E settings were not loaded. No provider, real payment or business notification was exercised.

- Build and owned database readiness: exit 0.
- Guarded migration smoke: exit 0; actual ready head **`journal_append_order`**.
- Financial PostgreSQL suite plus defensive replay module: **299 passed**, 2 existing FastAPI deprecation warnings, 532.36 seconds; exit 0.
- Copied JUnit: **299 cases**, zero failures/errors; **280** directory-classified PostgreSQL cases plus **19** replay-module cases. All 9 exact new transfer selectors passed.
- Frozen source check: passed.
- Owned Compose teardown: exit 0. Its console included an `Error while Stopping` message on a repeated test-container stop/removal entry; this message was not suppressed or treated as proof of failure/success. The parent separately queried Docker labels afterward: **zero owned containers, networks and volumes remained**.

Docker checks used a fresh isolated test database and did not migrate any deployed database. This is not evidence about production-role privileges or every isolation level.

## Local artifact provenance

The actual local gate entrypoints were `/tmp/ugc-financial-integration-gate.py` and `/tmp/ugc-financial-integration-compose-gate.py`; these local orchestration artifacts are not claimed to be versioned repository commands.

Full run `2e37452038fd`:
- `/tmp/ugc-financial-integration-2e37452038fd-coverage.xml`
- `/tmp/ugc-financial-integration-2e37452038fd-junit.xml`
- `/tmp/ugc-financial-integration-gate-result.json`

Standalone Docker:
- `/tmp/ugc-financial-integration-bafca292e988-result.json`
- `/tmp/ugc-financial-integration-bafca292e988-junit.xml`

Independent final review and parent evidence:
- `/tmp/ugc-financial-transfer-authorized-review.json`
- `/tmp/ugc-financial-transfer-authorized-parent-verification.md`
- `/tmp/ugc-transfer-authorized-red.log`

These paths record this local execution; they are not promised to exist on another checkout or in GitHub Actions. CI at a newly published head must be checked separately; no earlier PR's CI result is transferable.

## Remaining gates / prohibitions

Financial flags remain off. No merge, production or dev deployment, deployed migration, real payment or real business notification is authorized by this checkpoint. No deploy workflow was dispatched.

Outstanding scope includes complete assignment/manager-return lifecycle, trusted grade/canonical identity/cutover producer wiring, remaining case/cancellation/refund/payout writers and provenance, durable financial alerts, typed router/inbox/consumer DI, financial UI and remaining plan acceptance criteria. Legal/refund-window/launch-policy approvals are not invented. A verified draft slice is not launch readiness.
