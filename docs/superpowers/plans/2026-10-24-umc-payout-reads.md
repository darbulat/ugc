# Payout read context and bounded navigation implementation plan

Current bounded implementation status: frozen9gb accepted by independent source/
pure/actual PostgreSQL closure. Owned581passed/99.48% at unchanged98floor;
independent167passed including all65readerPG. Final routes are under
`/payouts/read/` (the early task examples below predate that explicit namespace).
Reports: `/tmp/umc-full-sprint-reports/task-9gb-finish-report.md` and
`task-9gb-independent-review.md`. This is backend read readiness only;9h1native
financial concurrency,9gcUI,6ccorrections and the shared gate remain separate.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the signed owner and current administrator a coherent, safe payout read context and bounded navigation before building the actual payout screens.

**Architecture:** A dedicated application read service consumes facts from a PostgreSQL repository within one fresh REPEATABLE READ READ ONLY transaction per response. It does not call writer methods, create a wallet, repair projections or take the payout command barrier. Existing mutation authority and own operation recovery remain unchanged. Exact decimal-string presentation is reused from stage9g-a.

**Tech Stack:** Python3.13, SQLAlchemy async PostgreSQL/PostGIS, FastAPI, existing strict signed TG/MAX principal, pytest/sysmon.

**Spec:** `docs/superpowers/briefs/umc-full-sprint/task-9g-payout-ui.md`, especially server capabilities, consistent context and bounded navigation; stage9g-a actual readable contracts and recovery are prerequisites.

## Global constraints

- Work only in the existing isolated full-sprint worktree; no commit, push, deployment, live transfer, publication of real legal terms or feature activation.
- Preserve default-off financial flags and the unchanged backend coverage floor98. Coordinate the exclusive PostgreSQL test slot withroot.
- Do not edit any frozen migration or schema. This stage adds read behavior and requires no new durable financial facts.
- Domain and SQL monetary values remain integers; EVERY payout money wire field, including nested history and observations, uses canonical decimal strings.
- Own reads remain available for existing active/pause/bot_blocked accounts, including while financial mutations are paused. Actual current active-admin authority is reread within each protected response snapshot.
- No plaintext requisites, ciphertext, fingerprint, key identifier, input hash or administrative evidence in owner context/list/detail/recovery.
- A capability is a conservative hint as of its response snapshot. It never replaces explicit acceptance, current expected version or mutation-time authority under existing barriers.
- Keep the emergency path for recording an actual bank observation against a real prepared execution while mutations are paused. That capability never authorizes a new bank transfer.
- No refund-window anchor, tax/legal status, minimum, fee, provider, fabricated document or legacy-balance conversion is introduced.
- Missing key and a syntactically valid wrong key have safe read blockers. Explicit malformed crypto configuration retains the existing fail-closed startup behavior; read availability applies to a bootable service graph. This stage does not substitute a key or change that factory contract.

## Review focus

- Missing or partially installed sources, an orphan movement, an unproved issuance or balanced-but-unproved payout history must not become a spendable zero or a reserve capability.
- Revoked roles and another user's copied cursor/request selector must not reveal the prior actor's protected data, even on the next page of an existing navigation flow.
- A receipt from an earlier version is historical; current actions must derive from the fresh authoritative request event and equal projection.
- A paused/missing-key installation must preserve safe history and actual-observation recording without implying that review/start/reservation can proceed.
- Late commits and mutable queue membership can change between page requests. Pagination must promise a consistent snapshot per response, not an undocumented immutable cross-request snapshot.

## File map

- Create `src/ugc_bot/application/payout_view_ports.py`: narrow immutable read facts, paging arguments and repository protocol.
- Create `src/ugc_bot/application/services/payout_view_service.py`: safe context/detail/queue/history DTOs, conservative capabilities and stable blocker codes.
- Create `src/ugc_bot/infrastructure/db/repositories/payout_views.py`: per-response read-only snapshot, table preflight, exact scoped keyset queries, financial proof reads and deterministic protected facts.
- Create `src/ugc_bot/miniapp/payout_view_api.py` and `payout_read_principal.py`: strict signed existing-only context/detail/preview/paged routes, typed trusted native identity, stable errors/no-store and existing wire serializer. Keep old9g-a route behavior separate; reuse its safe error boundary without changing writer/recovery semantics.
- Create `src/ugc_bot/container/payout_view_factory.py`: reader construction. Root owns main-API mounting and `container/service_factory.py`, `container/types.py` registration after the hook is importable.
- Create `tests/unit/test_payout_view_service.py` and `tests/postgres_financial/test_payout_views.py`: meaningful pure policy and real signed TG/MAX snapshot/navigation cases.
- Reuse existing actual publication, payout, bank observation, reconciliation and request fixtures; do not weaken old-revision retention tests.

## Root resolution of the independent design review

The six required clarifications in `/tmp/umc-full-sprint-reports/task-9gb-design-review.md` are accepted below. They are implementation requirements, not evidence that the read service exists. Stage9g-a remains source-frozen; no writer changes, new DDL or UI are added by this resolution.

### Existing-only principal and snapshot revalidation

New read routes carry a narrow trusted application read principal: canonical UUID, validated platform and native external ID. The resolver validates current configured TG/MAX HMAC and existing24-hour freshness before existing-user lookup; it never calls `set_user`, sets a default MAX country or changes roles. It accepts no body/cursor actor selector. Inside RR, reread the User with BOTH the same UUID and the validated platform's actual external-ID column, then current status/admin. A mapping change between resolver and snapshot denies access. Existing auto-creating principal helpers are not a reader shortcut. Add actual signed TG/MAX unknown-user, missing-country and mapping-race tests and assert no User/country/role/wallet writes.

### Capabilities and exact reserve preview

Context entry hints mean only `begin_request`, `store_requisites`, `read_own_requests` and, for a real current active admin, `read_admin_queue`/`read_admin_requirements`/`publish_requirements` as appropriate. They are distinct from permission to reserve an unspecified amount. Context reports recipient-wide source/reconciliation/debt/legacy/unmatched-observation blockers separately from item-specific checks.

Add a signed own read-only reserve preview accepting only own requisites ID, canonical positive money string and RUB in addition to auth. Select the SAME UUID-ordered positive-available obligation prefix for that exact amount as the writer; authenticate the chosen frozen requisites/current readable acceptance, then evaluate recipient-wide and selected-item guards in the response snapshot. Return exact requested amount, as_of, safe blockers and a conservative `can_reserve` hint. Return no item/contact/foreign-recipient list. Insufficient funds or incomplete checks mean false, never invented eligibility. An unrelated disputed item outside the selected prefix must not block a clear smaller request; a selected disputed item must block even if another clear item exists. Submission still performs the original independent locked writer checks; preview reserves nothing and requires explicit subsequent user action.

### Queue authority and bounded collections

SQL queue membership uses the latest immutable event, its complete projection proof, and equality with the mutable state. Missing/malformed/mismatched authority remains a discoverable `unavailable` review row BEFORE keyset limiting; a projection forged to clean paid/rejected cannot hide it. Healthy clean terminal rows are excluded, healthy terminal rows with an authoritative review blocker remain. Safe broken rows expose only immutable request ID/amount/mask/deadline and a reconciliation code, never an invented current state/version. Do not inner-join away a missing state or silently drop a DTO conversion failure. Pin projection-falsely-terminal, missing-state and cleared-blocker pages in real PG.

Context includes only the first bounded masked-requisites page, with explicit has_more/cursor; a separate strict own route continues `(recorded_at, requisites_id)` keyset navigation. Authenticate only returned snapshots and discard plaintext before DTO construction. Do not call the old locking/unbounded `requisites_for_actor` helper. New screens use bounded new own/queue/history/masked/requirements-history routes; old unbounded routes remain compatibility-only. Admin publication context distinguishes actual CURRENT effective requirements from the actual LATEST published version, including future-effective publications, so expected publication version is never guessed from the owner document.

### Separate action hints and exceptional observation context

- Review: current active admin, ordinary flags enabled, proven reviewable state and actual applicable recipient/allocation safety. It does not inherit start's bank-account/key prerequisites unless the existing writer needs them for this action.
- Reject: current active admin, ordinary flags enabled and proven nonexecuting/nonterminal reviewable state; evaluate the writer's release-specific guards. A new debt/current recipient pause/changed current terms alone is not a newly invented release prohibition. Real unresolved bank/correction/dispute/reconciliation guards still apply.
- Start: current active admin, flags enabled, proven approved state, actual stored allocations and safety, authenticated frozen requisites and configured origin account. Do not add new-readable-acceptance requirements to historical admin actions.
- Escalate: current active admin, ordinary flags enabled, proven current event/equal projection, nonterminal state excluding paid/rejected, actual original72-hour deadline and no prior escalation; it creates no payment or release.
- Reasoned reveal: current active admin, existing own-scoped request/frozen requisites and usable decrypt key; keep its distinct audited explicit command, independent of ordinary financial flags.
- Record actual observation: current active admin, actual existing request and a real retained intent plus storage sources. Pause/key loss/terminal or stale execution/projection mismatch can block application while the fact remains reportable. This hint never authorizes a new transfer or promises `applied=true`. Keep proven CURRENT execution context separate from real RETAINED intents for exceptional reporting, with protected fences/accounts only in admin responses.

Observation version metadata must be explicit. Prefer the actual proven current version; otherwise expose a clearly labeled actual immutable event version associated with that retained execution, without calling it current state authority. If no such source exists, return null/`retained_version_required`: the later operator form must explicitly supply its actual retained UMC version; no server/client default or fabricated1 is permitted. The existing writer still validates/retains the observation and refuses monetary application when authority/version does not match. Do not reconstruct current execution or a fence from a maximum timestamp, mutable row or paged subset.

### Source-proof and presence matrix

- Identity: actual `users` identity/status/admin columns, reread inside the snapshot.
- Amount display: installed raw `financial_obligations`, append-ordered `financial_movements`, `financial_wallets` with raw row presence; complete issuance bases and journal replay plus exact projection equality. Optional enrichment joins through rate snapshots cannot erase raw facts into empty history. Never use the helper that converts absent wallet to zero.
- Requirements/masked snapshots: actual payout requirements/requisites and all three readable companion tables/required columns, current document/hash/field-definition/acceptance integrity, and configured crypto for usability only. Missing companion remains honestly unreadable; history is not backfilled.
- Money readiness: journal proof PLUS P01 movement/allocation/request/intent/outcome/settlement authority, the legacy anchor column `payout_requests.payout_protocol`, nonlocking equivalents of actual legacy guard/case predicates, recipient debt/unmatched observations and selected stored-item/work dispute/correction facts. A display balance cannot substitute for any of these.
- Request/detail/queue: immutable request/requisites, latest event proof, equal state, actual immutable allocations. Protected execution/history additionally require actual intent/outcome/settlement/event sources and current-admin identity. Observation intake needs its minimal real request/intent/storage sources independently of money-readiness completeness.

Preflight required relation AND column presence before querying each source family, including old-schema `payout_protocol`; do not catch UndefinedTable/Column after aborting RR. Known-empty requires complete raw actor-scoped sources and no actual history; absent wallet WITH history is unavailable. Do not attribute an unscoped orphan to arbitrary owners using movement.actor_id. Use explicit source-integrity blockers, exact safe public-code/DTO allowlists and no SQL/exception/persisted arbitrary reason echoes. A full internal journal replay may read the actor's complete journal as proof; bounded outward history/request/queue collections must not materialize all rows and slice them.

### Task1: coherent own context and explicit source state

- [ ] Read the final9g-a service/repository/contracts after its source freeze. Identify reusable side-effect-free financial proof and readable-document helpers; do not call `_clear`, `_current_requirements`, `lock_money_scope`, reserve or writer reconciliation as a read shortcut.
- [ ] Write REDs for actual signed TG/MAX `/payouts/context`: current server actor/as_of, status, runtime reason codes, exact-string available/reserved only when known, actual readable requirements, safe masked snapshots and capability names. Include pause, missing/wrong key, unreadable legacy terms, genuinely empty v1 history, partial schema, missing wallet with history, orphan/invalid movement, projection mismatch and the existing P01 history-authority regression.
- [ ] Start the fresh read-only snapshot before EVERY SQL statement in this response. Read actual actor within that snapshot. Preflight complete required source families before touching optional relations; absent schema is explicit unavailable data, never a quiet zero and never an automatic migration.
- [ ] Validate the same immutable journal/issuance bases and wallet projection used by financial reconciliation. Distinguish known empty history from missing sources and mismatch. Preserve historical facts; do not upsert, flush, lock writers or repair anything. A display amount alone is not writer readiness.
- [ ] Derive conservative capabilities from current actor, config, actual readable current requirements, key/requisites authentication and the proven current financial prerequisites. Represent unknown/unimplemented checks explicitly as blockers rather than optimistic authorization. Unrelated obligations must not be mistaken for the specific allocations selected by a future reserve.
- [ ] Verify actual READ ONLY rejects an attempted write from the response session, no wallet appears for an empty actor, and an independently committed concurrent change cannot split one response into mixed snapshots. The next response must observe the fresh committed state.
- [ ] Run scoped unit/PG cases and inspect safe DTOs for forbidden fields and exact maximum money strings.

### Task2: authoritative request detail and admin actions

- [ ] Write REDs for owner versus current-admin detail, revoked admin, changed account status, original receipt versus current state, projection/event mismatch, stale execution, exact deadline equality, escalation already recorded, missing bank-account configuration, missing key and pause.
- [ ] Return safe owner request data plus current `version`, `allowed_actions`, safe blockers, `as_of`, server-computed overdue/deadline information. A foreign owner selector cannot reveal presence or protected facts. Do not invent an owner cancellation action.
- [ ] Compute administrator action hints from actual state and prerequisites. Review/start/reserve remain unavailable when paused. Start requires an actual approved current state and configured execution prerequisites. Reject is not a shortcut for an unknown/executing transfer. Escalation requires the actual original72-hour deadline and deduplicated event state.
- [ ] Protected current execution context comes from the real retained intent (execution ID, fence, prepared time, frozen origin account); no caller-supplied or inferred bank proof. Protected result reporting requires an actual existing execution and current admin, and remains separate from a new-transfer capability during pause.
- [ ] Reuse exact proof and safety rules where they can be shared without writer locks or changing mutation semantics. A newly observed dispute/debt/unmatched outcome invalidates fresh actions; the writer continues to reread authority at submission.
- [ ] Prove no protected execution/evidence/requisites fields reach owner detail and all detail/error responses are no-store.

### Task3: deterministic bounded own/queue/history navigation

- [ ] Write REDs with more than100 outstanding requests, equal timestamps, both terminal and blocked terminal rows, next-page ownership/role changes, malformed/cross-scope cursors, inserted requests and state changes between pages.
- [ ] Add bounded keyset own and queue endpoints (limit1..100). Use deterministic `(requested_at, request_id)` order and `limit+1`; filter current queue membership in SQL before limiting. Never fetch all requests and slice in Python. Preserve existing endpoints' compatible behavior where needed; the new UI uses the bounded contract.
- [ ] Cursor data is untrusted navigation, never authority. Validate a bounded versioned strict structure, aware timestamp, UUID, route/filter/actor scope; always reapply authenticated scope in SQL. Do not add an invented signing secret or persist credentials. Return a stable error for malformed or foreign-scope input.
- [ ] Each page has its own fresh snapshot/as_of. Explain in the contract that requests committed or changed between pages require refresh and may alter membership; do not claim a retained database snapshot across HTTP calls. Duplicate timestamps never cause duplicate/missing rows within a stable dataset.
- [ ] Bound protected history navigation with deterministic event version, intent prepared-time/ID, observation recorded-time/ID and settlement time/ID ordering, preserving applied/unapplied distinction and review reasons. If separate collections have separate cursors, validate each independently and keep current detail/execution context separate from a paged historical subset.
- [ ] Prove SQL-level bounds with actual PG data, current-admin checks on every page and absence of unbounded materialization.

### Task4: integration, verification and independent review

- [x] Announce importable factory/service hooks to root. Root wires the service and dispatcher key; keep source ownership separate from9g-a/9f/10b work.
- [x] Run actual signed TG/MAX API and per-response concurrency/privacy/source-readiness regressions plus all carried payout tests, Ruff/format/mypy and fresh sysmon scoped coverage with explicit `--cov-fail-under=98`.
- [x] Save exact command/results and remaining limitations in the task report. Announce all PG sessions ended before releasing the exclusive slot.
- [x] Request fresh independent read-only review of the complete9g-a/b boundary before9g-c screens. This is backend read readiness, not completed P01 UI, actual bank execution or release acceptance.
