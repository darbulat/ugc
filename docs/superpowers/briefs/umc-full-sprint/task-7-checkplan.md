# P01 backend implementation check plan

> Execute inline with TDD; no commits, live bank/message calls, feature activation or broad shared-tree gate.

**Goal:** An authenticated owner can reserve actual available journal funds using encrypted details and published real requirements; a current admin can review, reject, prepare and record evidence-backed manual bank outcomes without losing stale/unknown facts.

**Architecture:** Immutable requirements/details/request/allocation/event/intent/outcome/settlement facts, replayable request state, and existing immutable ledger/projections. Legacy request identity anchors have an explicit protocol discriminator; legacy daily indexes/statistics/callbacks remain legacy-only. Actual bank automation stays external.

**Tech stack:** Existing Python/SQLAlchemy/PostgreSQL/FastAPI signed TG/MAX ingress; cryptography AES-GCM with required externally configured key.

**Spec:** task-7-payout.md and approved root scope, Financial v1 ADR, canonical HTML P01/financial-v1.

## Task 7a: requirements, secure details, actual reserve

- [x] RED actual PG schema/index/protocol tests, freeze payout_schema.py + payout_models.py and financial_payout_v1 after campaign_foundation_v1; tell checkout/root immediately.
- [x] RED crypto missing key/tamper/context isolation and publication/current admin, then implement actual key config/crypto and signed requirements publication/requisites storage contracts.
- [x] RED actual capture→assignment→successful work→maturity→available→owner reserve, actor/ownership/idempotency/conflict/overspend/debt/case/mismatch; implement sorted User→wallet→item→obligation→request coordination, real allocations/journal links and immutable request events.
- [x] RED legacy daily index semantics, callback and statistic separation, cascade/history guards, direct SQL pointer/NULL/amount and immutable guards; implement narrow compatibility changes.

## Task 7b: review/manual outcomes/API/queue

- [x] RED current admin/versioned review/reject/prepared execution, reserve release only before execution and when clear; implement exact frozen scope/fence.
- [x] RED evidence-backed paid/failure/unknown, retained wrong amount/currency/stale settled, duplicate actual bank reference, rollback and independent admin races; implement append-only outcomes/settlement links with no bank I/O.
- [x] RED signed TG/MAX own/admin API and runtime construction; provide exact central hooks for root, no broad central ownership edits.
- [x] RED requested_at+72h queue/escalation dedup and paused/missing-config behavior; implement read/queue commands with no automatic payment or reserve release.
- [x] Scoped realPG/runtime/unit tests, Ruff/format/mypy and >=98% focused coverage; root owns broad gate.

## Review focus

- Unknown/stale/amount-mismatched actual bank facts remain durable and reserve is not released automatically.
- Current dispute and unresolved debt are checked under writer/item barriers even when outbox lags; no offset/forfeiture.
- Raw requisites never appear in read results, audit JSON, journal reason, logs or outbox.
- Public payload never supplies trusted actor/approval/allocation/balance or bypasses configured encryption/requirements.
- Existing legacy-only daily semantics and financial histories survive the protocol bridge and migration downgrade refuses populated facts.

External production prerequisites remain explicit: recipient/legal/terms requirements, actual protected evidence/reference and operator assertions, encryption key custody, payout activation and eventual selected bank provider/access. Synthetic tests are not approval evidence. Coupled refund/debt recovery follows root Task6c and is not claimed complete here.

## Approved correctness follow-up

- [x] Real PG RED→GREEN projection approval/version/execution/block corruption; complete resulting state frozen in immutable events, exact projection validation, safe unavailable reads, retained unapplied bank facts and explicit same-proof resolution.
- [x] Final post-follow-up fresh sysmon coverage gate and handoff report.

Verification details and external limitations are recorded in /tmp/umc-full-sprint-reports/task-7-report.md. The 103-test/98.96% checkpoint predates the projection follow-up and is not substituted for its final fresh gate.

Final post-follow-up evidence: task-7-final-v3-gate.log, 111 passed / 98.99%, fresh sysmon coverage and unchanged 98 floor; owned Ruff/format and mypy8 clean. Additional legacy compatibility: 11 PG and 39 unit/callback tests passed. Production source and DDL frozen; root owns independent review/shared gate.

## Independent-review P1 correction

- [x] Read the independent report and actual history probe; reproduce missing-authority stops for preserved v1 open reserve/paid history and the populated pre-P01 migration boundary.
- [x] Runtime readiness under held User/wallet/item scope requires accepted immutable P01 allocation/execution/settlement authority for bank-affecting v1 journal facts; preserve old facts/readability and do not classify legacy-only rows as v1 journal history.
- [x] Retain new bank observations/physical claims unapplied with exact replay; reject new money, review/start or settlement while authority is missing; existing projection consistency remains enforced.
- [x] Final owned gate 123 passed / 99.00% with explicit 98 floor, fresh sysmon coverage; legacy 10 PG + 39 unit/callback passed; mypy8/Ruff/15 formatted files clean. All owner PG sessions finished; source frozen, no further DB runs before root sequential recheck.

Evidence: /tmp/umc-full-sprint-reports/task-7-p1-fix.md and task-7-p1-final-gate.log. No 9g/6c/cross-producer authority, schema rewrite, live call, activation, commit or push was added.


## Stage9g-a contract extension

- [x] Exact decimal-string API presentation recursively preserves SQL/domain integers and retained command hashes; strict old integer/canonical-string inputs normalize before hashing.
- [x] Immutable actual admin-supplied document/schema and explicit bound acceptance; disabled/missing/opaque source remains honest, old facts/ciphertext are preserved.
- [x] Own barrier-protected operation recovery and masked requisites; no private cached fields, selectors, false absence during in-flight commit, key-loss read failure or automatic resend.
- [x] Route-level sanitized422/no-store/privacy follow-up, actual signed TG/MAX RED→GREEN.
- [x] Real prior-P01→actual child-chain companion migration plus original populated P1/history/projection/evidence controls; empty/populated immutable migration checks.
- [x] Final gate255passed/99.20% explicit98/sysmon; legacy10PG+52unit/callback, Ruff/mypy14/30format clean. All owner PG sessions ended, source/DDL frozen for root review.

Evidence: /tmp/umc-full-sprint-reports/task-9ga-report.md. Frozen P01 migration is unchanged; financial_payout_contracts_v1 follows campaign_digest_v1. The earlier Task7 UI note about integer JSON is superseded only at the API boundary: monetary responses are now exact strings, immutable stored facts remain integers. No9g-b/c/6c/provider/activation/fullgoal closure follows.


9g-a review follow-up: arbitrary service ValueError text is now normalized through an exact safe-code allowlist, including caught safety/masked reasons. Actual signed TG/MAX read/mutation RED→GREEN; latest pure payout120passed, helper100% coverage/explicit98, Ruff/mypy15/31format clean. The255/99.20PG checkpoint above predates this final source-only fix. No new PG run after root released the slot to9f; root owns post-fix PG carry and independent recheck.


Final no-PG privacy carry: a lowercase poisoned retained block reason also failed RED, so recovery now admits only exact known server block codes (including empty) and rejects unknown code-shaped content safely without rewriting history. Latest final pure gate task-9ga-public-errors-coverage.log:123passed,100% coverage of payout_contracts+payout_errors, explicit98/sysmon; Ruff/mypy15/31format clean. The255/99.20complete PG checkpoint still predates these bounded privacy fixes; root owns post-fix PG carry. All owner PG sessions remain ended; no further source/DB work scheduled.
