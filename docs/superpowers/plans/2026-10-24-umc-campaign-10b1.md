# Campaign 10b-1 Implementation Plan

> Execute inline with `superpowers:executing-plans` and TDD. No subagents, commits, pushes, shared gate or live calls.

**Goal:** Share authoritative binding-epoch consent, validate typed campaign content/filter/frozen-envelope contracts, and persist own draft revisions with a truthful aggregate audience preview.

**Architecture:** Retain the foundation's User → history → campaign lock order and caller-owned transactions. New domain/application/SQL/router modules expose focused root integration hooks; immutable draft history is separate from the existing foundation streams. No submission, moderation, reservation, delivery, response or UI implementation belongs here.

**Spec:** `docs/superpowers/briefs/umc-full-sprint/task-10b-campaign-review.md`, plus approved 10/10a briefs.

## Constraints and ownership

- Work only in the existing sprint worktree. Existing `campaign_service.py`/SQL `campaigns.py` may change narrowly to consume the shared resolver. No history writer, central config/models/container/main API, financial, social or HTML/CSS/JS edits.
- No PostgreSQL operation or migration file until root grants the exclusive slot and actual head after 9f. Keep this step pending meanwhile.
- Legacy stats `fetched_at`, `legacy_profile` and caller/source-name assertions cannot establish successful metric time. Missing independent measurement proof is unknown.
- Exact five-locale envelopes include frozen sender/template, actual reserved UUID/native URL, complete text/action bytes, and per-locale/aggregate digests. Draft saving does not seal a moderated envelope; future submission must lock the actual advertiser brand source.
- Preserve current role/grant/policy checks, exact terms and original operation-key semantics; no arbitrary audience list/contact/export. Reads are repeatable-read/read-only. Keep 98% coverage floor without exclusions.

## Execution ledger

- [x] 1. RED/GREEN shared consent epoch. `tests/unit/test_campaign_consent_epochs.py` proves genuine interruptions, repeated identical observations, exact retained receipt/context, missing proof and same authoritative settings/allow predicate. Add `application/services/campaign_consent.py`; narrow SQL context enrichment/receipt-proof projection and foundation service use. SQL regressions follow in step 4.
- [x] 2. RED/GREEN pure contracts. `tests/unit/test_campaign_review_contracts.py` proves strict content/segment/action schemas, normalization, metric unknown behavior, exact all-five-locale envelope digests and 4096/4097 technical boundaries. Add `domain/campaign_review.py` and a focused pure envelope module if needed. No mutable dictionaries survive in frozen DTOs.
- [x] 3. RED/GREEN draft/preview service and router with in-memory test ports. Add `application/campaign_review_ports.py`, `application/services/campaign_audience_service.py`, `application/services/campaign_review_service.py`, `miniapp/campaign_review_api.py`. Save exact actor-scoped immutable revisions, own list/detail, stale/version/replay behavior; actual aggregate preview deduplicates UUID/IG/normalized destinations with disjoint exclusion reasons and no private output. Router uses supplied strict principal and root-injected services/transactions only.
- [x] 4. AFTER ROOT SLOT: real SQL RED, then migration/adapter GREEN. Add `tests/postgres_financial/test_campaign_drafts.py`, `test_campaign_consent_epochs.py`, `test_campaign_metric_provenance.py` and `test_campaign_review_api.py`; preserve all carried foundation/signed-auth regressions. Implement `infrastructure/db/campaign_review_models.py`, `repositories/campaign_review.py`; create one root-approved additive migration against the assigned actual head. Test own-only revision persistence, current grants/policy, epoch races, read-only snapshot, failed collector's actual touch path, lossless rollback/immutability/downgrade refusal and real signed ASGI for both hosts. No fake monetary/provider outcome.
- [x] 5. Scoped verification/review handoff. Ruff/format/mypy on owned files; scoped sysmon coverage at 98%; real SQL/migration checks only in slot. Report integration hooks, exact commands/evidence and remaining 10b-2/10c. Root runs independent review/shared gate; do not claim M02 complete.

Pre-flight: step 1 produces `consent_context` and `effective_consent_reason` consumed by settings and step 3 preview; step 2 strict DTOs are serialized by step 3 and reconstructed by step 4. Use identical persisted canonical payload/digests at each boundary. Step 4 depends on root's schema slot, not a guessed migration parent.

Ruling: full-suite and commit instructions in generic skills are superseded by root's explicit shared-gate/slot/ownership instructions. Focused unit tests may run now; integration evidence remains pending until authorized.

Progress (2026-10-24): the initial source-only checkpoint was 125 passing cases plus one unique later immutable-envelope regression, with scoped Ruff/mypy green. Root then explicitly released exclusive PostgreSQL/schema ownership against actual sole head `messenger_linking_v1`. Prepared real SQL tests observed five missing adapter/model REDs before creation; the announced additive child `campaign_drafts_v1` is implemented. Actual container/main-router signed Telegram/MAX, SQL consent epochs/identical witnesses, separate-Container edit race, pending-revoke refresh, rollback, immutability, failed metric touch, parent-schema setup guard and migration retention/roundtrip checks pass. Numeric metrics remain unknown; geography matches exact stored values only.

Final fresh scoped sysmon gate: **198 passed in 28.24s; 99.76% across all 13 owned/narrow runtime modules including the actual migration**, explicit unchanged `--cov-fail-under=98`, no artificial exclusions. Ruff/format check: 21 files clean; mypy: 13 source files clean. API privacy includes constant validation/error bodies, explicit known-code whitelist, generic unexpected503 and no-store all responses. All PostgreSQL sessions/engines ended; fresh other-client count zero, then verification engine disposed and root notified of slot release. Full evidence and exact runner: `/tmp/umc-full-sprint-reports/task-10b1-report.md` and `run-task-10b1-scoped.py`. Root independent review and shared gate remain pending; full M02 submission/moderation/delivery/UI/responses/reports remain later scope.
