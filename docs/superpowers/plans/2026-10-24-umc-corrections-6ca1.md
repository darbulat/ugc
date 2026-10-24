# UMC Corrections 6c-a1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` for the approved inline execution method. Steps use checkbox (`- [ ]`) syntax. This document authorizes no implementation, migration, database operation, commit or deployment; root releases those separately.

**Goal:** Persist actual correction evidence and safely apply only full captured selection refunds for an own client's unassigned, undelivered positions after their agreed selection deadline, cancelling only their original pending client-referral liability.

**Architecture:** Append immutable commands, case events, observations, matches and applications; derive a separate replayed projection and live funding view. A shared physical-proof authority covers new refunds and P01, including existing immutable P01 owners. The client capture consumer owns delayed original gross assessment plus eligible compensation in its existing caller transaction, before its successful consumer receipt.

**Tech Stack:** Python 3.13, typed application ports, SQLAlchemy 2 async sessions, PostgreSQL and Alembic, FastAPI/Pydantic, pytest/pytest-asyncio, existing integer financial arithmetic and signed Telegram/MAX principals.

**Spec:** `docs/superpowers/briefs/umc-full-sprint/task-6c-corrections-design.md`, especially “First implementation boundary: Stage6c-a1”; independent scope assessment `/tmp/umc-full-sprint-reports/task-6c-design-review.md`; canonical `docs/product/UMC-developer-sprint-2026-10-22.html#financial-v1`, R01/R05/T01/P01 and Task 6 of `docs/superpowers/plans/2026-10-23-umc-product-sprint.md`.

## Global Constraints

- Positive scope is full selection-component refunds for captured, unassigned, undelivered positions after the actual agreed selection deadline.
- The authenticated own client explicitly chooses refund instead of extension; a current active admin reviews exact source/due versions.
- Amount comes from original captured allocation (50000 minor per eligible position), never caller-selected ledger entries.
- A reviewed manual observation, exact match and only pending client-referral cancellation complete this slice.
- Actual30paid/25delivered/5returned must reconcile to1250000minor selection base.
- Frozen10% client original150000 pending becomes125000 pending plus25000 cancelled. Do not assert client availability.
- A missing original client assessment leaves the exact reviewed match pending application. The delayed capture consumer may establish original gross pending once and apply the eligible cancellation in that SAME caller transaction before its successful consumption receipt.
- A known no-referrer potential instead has a durable zero-liability assessment, no invented recipient/zero journal. Coverage unavailable cannot become zero liability.
- Gross capture, payment-time snapshots, successful consumer receipts and original fulfillment remain immutable and reloadable.
- Observations and proof ownership survive expected application refusal through a bounded savepoint; outer transaction failure rolls back the entire command.
- Assigned/delivered positions, partial component amounts, hold/available/reserved/executing/unknown/paid, accompaniment, management and replacement remain unsupported for positive application in a1.
- Unsupported actual facts remain retained cases and block affected forward scope. No positive money/debt/release on these paths.
- No client close/maturity/available release, post-delivery refund-window anchor, repayment application, replacement writer, accompaniment proration, generic positive adjustment, UI, provider activation or invented legal/bank/pilot fact.
- Preserve WorkFinancialGuard and legacy financial guards. No external I/O in a transaction. Sorted prospective User and wallet barriers precede every order/payment/history/item/case/payout lock; no newly discovered late User lock.
- Every money wire field, including nested observations/history/results, uses canonical decimal strings; SQL/domain values stay integers. Strict new ingress accepts strings only for money.
- New ingress resolves only an existing signed TG/MAX identity. It never creates a User or sets country/roles; its trusted native identity is revalidated against the same canonical UUID after the first actor User barrier.
- New companion migration follows the actual coordinated head; frozen schema and historical migrations remain unchanged. Independent review and the unchanged98% floor are required before widening this boundary.

## Review Focus

1. An actual successful refund arrives before local capture: retain the original identity/proof, create no capture/allocation, block only sufficiently correlated scope, and require a fresh same-intent reviewed match after real capture (Tasks 3–6).
2. A delayed client assessment encounters a reviewed refund: commit original gross assessment and complete eligible compensation together, including known absence, or publish no successful consumer receipt (Task 6).
3. A bank proof first appears as an unapplied historical P01 result: its ownership still prevents refund reuse under the same configured namespace and mutex (Task 3).
4. A correction arrives between delivery prepare and accepted transport outcome, or between payout review and result: preserve actual transport/bank evidence, refuse affected forward application and retain reserve (Task 5).
5. A different admin/worker or a new proof repeats the same component: operation replay, cumulative capacity and source-entry linkage prevent duplicate cancellation without suppressing real observations (Tasks 4 and 6).

---

## Execution and coordination boundary

- This is plan-only work on baseline `6505af2` plus the shared uncommitted full-sprint work in `/home/bulat/.codex/worktrees/umc-full-sprint/ugc`. Inspected source is feasibility evidence, not a frozen future patch base.
- Do not start from or modify the dirty primary checkout. Do not create a second worktree, start agents, run tests, inspect a live database, or create schema/migrations while acting on this planning assignment.
- At execution, re-read the approved spec and actual changed-file ownership. P01 service/repository integration requires root's explicit release. Historical 9f/9ga/9gb/10b slot assignments from planning are superseded by their bounded accepted checkpoints; they grant this slice no slot. Task1 pure contracts are accepted. Later tasks remain unreleased until the next explicit root checkpoint.
- Root must provide both an exclusive PostgreSQL/schema slot and the actual coordinated head after all earlier writers. Never infer `down_revision` from this plan, from today's files, or from the currently visible `messenger_linking_v1`. Create the new file only after that release.
- No commit/push/shared gate until root requests it. Each task ends in a scoped verification/report checkpoint instead of an unsolicited commit. Root owns independent review and the final unchanged-98% shared gate.
- Keep positive commands unreachable until Tasks 3, 5 and 6 are complete together: both producer types use the common authority, all live guards are wired, and delayed assessment is atomic. A temporary refund-only proof table is not an acceptable intermediate release.

## Actual seams and file ownership

Existing sources to reuse, without changing their historical meaning:

- `application/services/paid_item_service.py::FinancialQuote` / `build_quote` and `repositories/financial_items.py::_payload` freeze 30 positions, selection due, client, terms and quote key. `order_items.selection_due_at` and `quote_payload` are captured-immutable; there is no editable due-version field. Use a canonical source digest, not a fabricated numeric version.
- `repositories/financial_capture.py::{intent_id,capture_id,SqlAlchemyFinancialCaptureRepository.capture}` produce the real `financial.capture_intent`, payment allocations and `financial.client_snapshot_requested`; provider is `yookassa_telegram`, original account comes from configured Telegram payment account. `PaymentSuccess` carries actual protocol source time. Do not manufacture a capture by inserting fixture-like rows into this producer.
- `repositories/entitlements.py::SqlAlchemyClientEntitlementRepository.load_capture` validates the full gross source but currently rejects refunded/cancelled item state. `repositories/selection_delivery_funding.py::SqlAlchemySelectionFundingRepository` already accepts corrected siblings; it must become a compatibility delegate to the same gross validator, not a second correction policy.
- `ClientEntitlementService.handle` locks prospective client/referrer/existing grounds, issues per-item `client-selection:{payment_id}:{paid_item_id}`, then writes `financial_client_assessments`. `FinancialEventRouter.route` and `OutboxPublisher` already run this handler and consumption in a caller transaction. Do not move compensation to a second outbox event.
- `FinancialLedgerService.transfer` intentionally accepts lifecycle transfers only. `JournalMovement` and replay already support linked `reversal`; the new trusted refund producer calls repository append/projection through a narrow compensation service, without widening `transfer` or exposing raw journal input.
- `SqlAlchemyFinancialLedgerRepository.get_entry_ref('issue:' + business_key)` gives the actual issuance entry UUID. `IssuedObligation.entry_id` is not assumed to equal the appended movement row ID. `PotentialBasis.assessment_id` identifies a durable `financial_audit_events` potential; retain that reference for zero liability.
- `PayoutService._result` retains actual paid results and uses `application_savepoint`; `payouts.bank_reference_lock/receipt_used` currently protect payout-only `account:reference` identity. Replace their internals with the common authority, keeping prior command payload hashes/receipts and current P01 result-state work intact.

New focused source files planned:

- `src/ugc_bot/domain/corrections.py`: immutable evidence/state/component/compensation values, strict validation, replay and pure cumulative target arithmetic.
- `src/ugc_bot/application/correction_ports.py`: authenticated command DTOs, source/repository/guard/compensation interfaces.
- `src/ugc_bot/application/physical_proof_ports.py`: configured physical identity, owner and shared authority protocol.
- `src/ugc_bot/application/services/correction_service.py`: own request, current-admin review, durable manual observation and fresh exact matching command orchestration.
- `src/ugc_bot/application/services/correction_funding_guard.py`: live component funding and unresolved blockers; no User locks.
- `src/ugc_bot/application/services/client_refund_compensation.py`: trusted pending-only calculation/application and delayed-assessment coordination hooks.
- `src/ugc_bot/infrastructure/db/correction_schema.py`, `correction_models.py`, `repositories/corrections.py`, `repositories/physical_proofs.py`: new additive facts/projection, source loading, ordered barriers and shared proof authority. New migration path is `src/ugc_bot/infrastructure/db/migrations/versions/financial_corrections_a1.py`; its parent is deliberately not assigned here.
- `src/ugc_bot/container/correction_factory.py`, `miniapp/correction_api.py`, `miniapp/correction_wire.py`, `miniapp/correction_principal.py`: production graph and strict existing-only own/admin JSON ingress, with no HTML/CSS/JS changes.
- `tests/helpers/corrections.py`; unit/application tests and the PostgreSQL files named in the tasks below. Helpers contain synthetic fixture construction, never production bank authority.

Existing integration files planned: `application/entitlement_ports.py`; `application/services/{client_entitlement_service,work_entitlement_service}.py`; `infrastructure/db/repositories/{entitlements,selection_delivery_funding,paid_selection,paid_selection_delivery,item_assignments,payouts}.py`; `application/services/payout_service.py`; `container/{repository_factory,service_factory,payout_factory,paid_selection_delivery_factory}.py`; `infrastructure/db/models.py` for new metadata registration only; `config.py` for the optional configured manual source identity described in Task 3; `miniapp/api.py` for router inclusion. Do not alter frozen `financial_schema.py`, `financial_lifecycle_schema.py`, `payout_schema.py`, `payout_contract_schema.py`, old migration files or their builders. The two existing runtime ledger callers are client/work consumers; guard their forward issuance and work maturity at those actual producer boundaries. The ledger remains an internal arithmetic primitive, not a new ingress.

## Shared contracts to pin before implementation

Domain records are frozen dataclasses/tuples with copied canonical payloads; timestamps are aware UTC, identifiers are nonzero UUIDs, monetary values are bounded integers. Source hashes use the existing canonical hashing convention. Public DTOs contain no actor role, beneficiary, allocation key, journal UUID or confirmation boolean.

`correction_ports.py` defines these commands, all keyword-only with `actor_id: UUID`, `operation_key: str` and substantive `reason: str`:

- `RequestSelectionRefund(order_id: UUID, paid_item_ids: tuple[UUID, ...], expected_source_hash: str, existing_case_id: UUID | None = None)`: explicit refund choice via command type; exact current own client only. Selected items are a unique nonempty sorted set. Requested money is server-derived. Ineligible own positions may create a retained review-required case, never positive permission.
- `ReviewSelectionRefund(case_id: UUID, expected_version: int, expected_source_hash: str, decision: Literal['approve','reject'], evidence_reference: str, evidence_hash: str)`: re-read current active administrator, persisted request and exact due/scope. Approval freezes the original selection allocation bundle. Rejection never negates observed bank facts or clears their blockers.
- `RecordManualRefundObservation(case_id: UUID | None, known_order_id: UUID | None, known_capture_intent_id: UUID | None, original_payment_reference: str, bank_account_label: str, bank_reference: str, amount_minor: int | None, currency: str | None, occurred_at: datetime | None, reported_component: Literal['selection','accompaniment','management','replacement','unknown'], evidence_reference: str, evidence_hash: str, expected_version: int | None)`: current active admin only. Input is a retained manual factual report; source/provenance is always server-set `manual_admin_observation`. No field can make it provider-verified. A successful physical report with mismatched/missing scope or stale application version remains durable/unapplied.
- `MatchSelectionRefund(case_id: UUID, intent_id: UUID, observation_id: UUID, expected_version: int, expected_source_hash: str, evidence_reference: str, evidence_hash: str)`: fresh admin review, same original intent, no caller allocation bundle/amount/beneficiary; derives all from approved request and real capture. This is also the explicit same-intent retry path after an expected refusal. Capture arrival alone never invokes it.

`CorrectionPrincipal` reuses the frozen9h1 `AuthenticatedMessengerPrincipal(user_id, platform, external_id)` and existing-only `resolve_financial_principal`; a thin correction error adapter is allowed, not another account-creating resolver. The HTTP envelope accepts none of its selector fields. `CorrectionService.execute(command: CorrectionCommand, *, principal: CorrectionPrincipal, session: object) -> dict[str, object]` writes an immutable original command receipt. At the first existing COMPLETE SORTED prospective User barrier it verifies command actor equals principal.user_id and the current native external-ID column still maps to that same UUID, then current role/status before downstream economic scope or action. No actor-only preliminary User lock is introduced; the minimum immutable routing reads needed to discover that complete set remain allowed. Authentication proof is not a command field or part of its economic idempotency hash; no initData/token is persisted. Internal delayed compensation uses its trusted retained match/capture interface, not an optional HTTP proof bypass.

`get_for_actor(case_id: UUID, principal: CorrectionPrincipal, *, session: object) -> dict[str, object]` returns fresh own-safe state; `get_for_admin(...)` and `list_exceptions_for_admin(principal: CorrectionPrincipal, *, session: object)` perform the same current identity revalidation and require current active admin. Own views omit private bank/evidence fields. An authenticated current replay returns its stored result after changed-payload checking; any new mutation revalidates authority/version/scope. Original receipt and current state are separate fields/read operations.

Each case event stores `case_id`, contiguous positive `version`, command/source IDs, actor/reason/evidence references, recorded time and **full** canonical `result_state`. State keeps request/review/match/application status separate, observation IDs and blockers explicit. `replay_correction_events(events) -> CorrectionState` verifies chain identity/versions/full result content; repository compares this state to its projection. Corrupt projection yields retained observation plus `state='unavailable'` on observation commands, no forged event or money; request/review/match fail closed. Reconstructing or repairing projection is outside command authorization.

`ComponentFunding` carries original `allocation_key`, payment/item/component/currency, immutable `gross_minor`, replayed `cumulative_refund_minor`, `net_minor`, unresolved observation/case IDs and state consistency. `CorrectionFundingGuard.load_item(paid_item_id: UUID, *, session: object) -> tuple[ComponentFunding, ...]` and `require_forward_clear(paid_item_id: UUID, *, session: object) -> None` read under already-held barriers and add no User/wallet locks. A known early observation may block an order/known intent before items exist; insufficient correlation stays an exception, without targeting arbitrary orders. Net is gross minus **applied** component facts, never a selection-state deduction or an observation total.

`ClientRefundCompensation.apply_matched_for_capture(capture: ClientCapture, *, assessment: OriginalGrossAssessment | None = None, session: object) -> tuple[UUID, ...]` applies eligible ready matches after the exact original gross assessment is established. Outside the capture consumer, missing durable assessment returns awaiting-assessment, never applied. Inside that consumer, `OriginalGrossAssessment` is an internal immutable server value constructed from the exact validated obligations/covered potentials just established or reconciled in the SAME caller transaction after `_issue`, including capture/event/source hash and actual basis/potential identities. It is not a boolean, body input, new receipt or caller-selected grounds. The hook validates those actual facts under the already complete scope and does not demand the intentionally still-absent consumer receipt. Only after compensation succeeds does `save_receipt` publish the original successful assessment, followed by consumer success. Failure rolls back issuance/potentials, compensation and both success facts together. `prepare_original_assessment(capture: ClientCapture, *, session: object) -> tuple[UUID, ...]` returns only exact reviewed eligible matches allowed through that historical gross-assessment path; unresolved/unmatched/unsupported scope refuses it. These are internal server-loaded hooks, never request body flags.

## Task 1: Pin pure evidence, state and compensation contracts

Accepted bounded checkpoint:88pure tests,100% of497executable statements in the
three new runtime modules at the unchanged98floor; scoped quality clean.
Fresh independent source review reran88cases and found no bounded issue.
Report:`/tmp/umc-full-sprint-reports/task-6ca1-contracts-review.md`.
No correction runtime/wiring/schema/migration or positive application is claimed.

Task2 root ruling:the frozen `CorrectionScope` lacked the case/subset routing
needed to reload an unavailable pre-capture scope. Root permits ONLY optional
`case_id: UUID | None = None` and
`selected_paid_item_ids: tuple[UUID, ...] = ()` plus validation/canonical copied
sorting/uniqueness (nonzero UUIDs,selected max30) and targeted pure tests.
These are explicit port facts,not a SQL-private subclass or invented source.
Discovery freezes the same actual case/subset; re-read cannot fall back to all
order positions. Required missing routing is unavailable; changed prospective
scope needs whole-transaction refresh,no late User. Record fresh RED→GREEN and
coverage; Task1's historical88-case acceptance predates this small amendment.
Its fresh independent review is required with Task2; other Task1 fields remain
frozen and no economic command/hash change is authorized.

**Files:** Create `domain/corrections.py`, `application/correction_ports.py`, `application/physical_proof_ports.py`; create `tests/application/services/test_correction_contracts.py` and `test_client_refund_math.py`.

**Interfaces:** Produce the commands, `CorrectionState`, `ComponentFunding`, `replay_correction_events` and `cumulative_cancellation_target(base_minor: int, cumulative_refund_minor: int, frozen_rate_bps: int, currency: str) -> int`. Consumers use the shared signatures above; no financial transfer command takes a caller-created `JournalMovement`.

- [x] Write RED tests for exact integer/UUID/UTC validation, empty/duplicate item sets, full-result replay, changed source/result state and independent request rejection versus retained successful observation. Assert boolean money, floats, unbounded integers and mutable aliased payloads fail.
- [x] Write arithmetic RED cases using existing `commission_minor`: `target = E(B) - E(B - cumulative_refund)` and `delta = target - already_source_linked_cancelled`. Include zero and full capacity, negative/over-capacity rejection, frozen override rates, and a rounding discriminator: `B=50000, rate=333, cumulative=15` gives target `0`, then cumulative `30` gives target `1` (second delta `1`); separately rounded `E(15)+E(15)` would stay `0`. This pure test does not enable partial-component application.
- [x] Run `uv run pytest tests/application/services/test_correction_contracts.py tests/application/services/test_client_refund_math.py -q`; expect failure for missing contracts/functions, not infrastructure errors.
- [x] Implement only these pure contracts and replay. Existing `commission_minor` is the sole half-up calculation; no new percentage formula or current-grade lookup.
- [x] Re-run the same command; require pass, then scoped Ruff/mypy. Report this task to root; do not commit or enable routes.

## Task 2: Add authoritative correction storage and source loading after the schema release

Root execution release,2026-10-24:Task2ONLY now owns the exclusive private
schema/PG slot after9h1's independent zero-resource release. Root freshly checked
the sole static migration head and assigns
`financial_corrections_a1.down_revision = 'campaign_drafts_v1'`. The Task2 file
map below and a single metadata-registration import are released; Task1 stays
frozen except the bounded scope-routing amendment above. Later runtime/wiring/
producer cutover remains unreleased. No positive
correction command may become reachable from this storage checkpoint. Other
active owners9h2/9gc2 have no PG access. Preserve release/cleanup evidence and
obtain independent review before widening the boundary.

**Files:** Create `correction_schema.py`, `correction_models.py`, `repositories/corrections.py`, future `migrations/versions/financial_corrections_a1.py`; modify `models.py` for metadata registration. Create `tests/postgres_financial/test_correction_schema.py`, `test_correction_sources.py`, `test_correction_migration.py`, `tests/helpers/corrections.py`.

**Interfaces:** `SqlAlchemyCorrectionRepository.discover_scope(command, *, session) -> CorrectionScope`; `lock_scope(scope: CorrectionScope, *, session) -> None`; `load_scope(scope, *, session) -> CorrectionScope`; `state_authority(case_id, *, session) -> tuple[CorrectionState | None, bool]`; immutable `command(actor_id, operation_key, *, session)` / `save_command(...)`; `application_savepoint(*, session)`; append-only fact writers; `live_funding` behind the guard. `CorrectionScope` freezes client/order/intent/capture/payment/allocation/due/quote/assignment/delivery/ground source identity and complete prospective actor/wallet sets, with a canonical source hash.

- [x] Wait for root's explicit schema/PG slot and actual parent. Re-read released P01 files and actual migration graph. Only then write failing schema/source/migration tests and the new migration; set its `down_revision` to root's actual assigned head.
- [x] Plan these new tables: `financial_correction_commands`, `financial_correction_cases`, `financial_correction_events`, `financial_correction_requests`, `financial_refund_intents`, `financial_refund_observations`, `financial_refund_matches`, `financial_refund_applications`, `financial_refund_component_applications`, `financial_refund_liability_assessments`, `financial_correction_states`, plus `financial_physical_proof_claims` (Task 3). Facts are immutable on UPDATE/DELETE/TRUNCATE; only states are mutable/replay-checked. Early intent fields for capture/payment/allocation stay nullable; later match stores a new frozen source bundle, never updates the earlier fact.
- [x] RED assertions: unique actor/key and case/version, full-result event replay, application/match uniqueness, amount/currency bounds, exact source relationships and cumulative component capacity under independent sessions. Use original `payment_item_allocations.allocation_key` (text), not an invented allocation UUID. Application lines freeze prior/new refund bases and original obligation/potential, original issuance movement, frozen rate/override, target/already-cancelled/delta and produced movement ID.
- [x] Require a deferred database application guard to verify each linked cancellation against the same original client obligation/item/payment/selection allocation/RUB and its actual issuance entry; validate application totals atomically, reject a partial bundle, and verify zero-liability lines reference a covered no-recipient potential with no journal movement. Existing gross item/allocation/quote immutability remains unchanged.
- [x] Build the 30-position fixture from actual `test_order_intake.py::{intake_env,command,service}`, actual quote, invoice/capture producer and immutable allocation records. Adapt existing signed receipt generation from `test_v1_capture.py::telegram_receipt` to the actual `1500000` self-service total. Seed referral binding before capture as in `test_client_entitlement_runtime.py::seed_attribution`, not by editing captured snapshots. Keep an alternate with-manager quote to prove accompaniment exclusion. Use a controlled clock **after** frozen due; never mutate captured due to make a refund eligible.
- [x] Source RED cases: foreign item/order/client, incomplete allocation set, changed quote/terms/due digest, any historical assignment, accepted delivery, creator/manager ground, corrupt state and absent actual due agreement evidence. No assignment ever plus no accepted-delivery fact is the a1 unassigned/undelivered criterion. A mutable `paid` state alone proves neither condition. Read real quote/intake due evidence; insufficient old data is unresolved, not retrospectively agreed.
- [x] Pin digest actor independence:the same actual source/subset yields the same expected source hash for the own client and a distinct reviewing admin. Native proof,actor ID,prospective lock sets and private adapter metadata are not economic source fields. A changed selected subset or actual allocation/due/quote/source fact changes the digest; explicit routing never permits an all-order fallback.
- [x] Run `uv run pytest tests/postgres_financial/test_correction_schema.py tests/postgres_financial/test_correction_sources.py tests/postgres_financial/test_correction_migration.py --require-financial-postgres -q` against root-approved isolated test environment; first observe RED, then implement minimal new additive storage/source loading and require GREEN. Migration tests upgrade from the assigned real parent, preserve prior command hashes/ciphertext, compare new metadata invariants, and refuse destructive downgrade with facts. Do not amend frozen builders.

Accepted bounded Task2 checkpoint: final builder132cases/562statements100% at
unchanged98floor; independent132cases43.35s plus all four original/residual
reproductions7.02s passed,14hashes unchanged. Capture and scope findings closed,
including nullable early client and case-only later request. Report:
`/tmp/umc-full-sprint-reports/task-6ca1-storage-residual-independent-review.md`.
This accepts storage/source and the narrow Task1 routing amendment only. Tasks3–7,
shared proof producer cutover, compensation consumer, API and fullAC9 remain open.
PG was explicitly released with fresh zero resources; root granted it to9h2.

## Task 3: Cut P01 and refunds over to one physical-proof authority

**Files:** Create `repositories/physical_proofs.py`; modify released `repositories/payouts.py`, `services/payout_service.py`, `container/payout_factory.py`, `config.py`; use Task 2's new claim table. Create `tests/postgres_financial/test_physical_proof_cutover.py`; extend `test_payout_recovery.py` and `test_payout_defensive.py` for carried P01 regressions. Unit-test identity encoding in `test_correction_contracts.py`.

**Interfaces:** Use the accepted `PhysicalProofIdentity(source, account, direction, reference)`, `PhysicalProofOwner(producer, intent_id, observation_id, command_id)` and `PhysicalProofAuthority.lock/owners/claim` exactly. `SqlAlchemyPhysicalProofRepository(source_id: str, canonical_account_id: str, clock: Clock)` uses only server configuration; `resolve_manual_identity(bank_account_label: str, reference: str, *, direction: Literal["incoming", "outgoing"]) -> PhysicalProofIdentity` returns a recognized identity or raises the bounded unavailable exception. Missing/unknown mapping is never an empty owner set. Canonical source/account normalization preserves existing P01 trimming and never guesses a provider. No parallel key/owner/result family is introduced.

- [x] RED tests first: new payout→refund and refund→payout reuse fails for different intents, including first successful-but-unapplied result; fresh same-intent reconciliation may apply once. Different recipients do not create namespaces. Blank/unrecognized labels are durable exceptions. `('a:b','c','outgoing','r')` and `('a','b:c','outgoing','r')` encode differently. Direction and source are physical namespace components, not body-selected bypasses.
- [x] Add the explicit optional server setting `FinancialConfig.manual_bank_source_id` / `FINANCIAL_MANUAL_BANK_SOURCE_ID`, default blank, alongside existing `manual_bank_account_id`. No guessed provider ID/default. Synthetic tests configure an explicitly synthetic source/account. Missing configuration allows retained observations but refuses trusted ownership/application. Actual deployment must supply the true source/account mapping; this work grants no provider access or bank verification.
- [x] Under one common transaction advisory mutex over canonical JSON-array/length-delimited `(source, account, physical direction, reference)`, inspect both new immutable claims **and** immutable existing P01 paid outcomes/settlements. Map historical rows only when their actual retained account/intent is recognized by the configured source/account mapping. Include unapplied `status='paid'` outcomes, and collapse multiple exact observations of the same request/execution to that owner. Multiple conflicting historical owners remain review-required. Unknown labels remain retained exceptions. Do not insert invented historical claims, change historical rows, or pretend a mapping is verified when absent.
- [x] Run a migration-cutover RED fixture with a real pre-companion P01 successful unapplied outcome and another with a settled outcome, then upgrade through the assigned head. Refund reuse must see both as owners. In a two-connection race, P01 and refund must use that **same** mutex before any success check/claim. Preserve old operation payload hashes and replay receipts.
- [x] Replace `payouts.bank_reference_lock/receipt_used` internals and P01 observation integration with the common authority. A recognized successful paid observation claims at observation time, outside its economic savepoint, even when emergency gates, stale state, missing crypto or safety prevent application. Preserve both the actual observation and original proof owner on conflict. A later different command cannot adopt/reassign it. Keep existing reserve and state-result behavior.
- [x] Run `uv run pytest tests/postgres_financial/test_physical_proof_cutover.py tests/postgres_financial/test_payout_recovery.py tests/postgres_financial/test_payout_defensive.py tests/postgres_financial/test_payout_runtime.py --require-financial-postgres -q`; require RED then GREEN and released P01 regressions green. No refund ingress until this integration passes independent review.

### Task3 pre-release source alignment and coordination

Root read-only inventory after the storage freeze: the accepted pure port is
`PhysicalProofIdentity(source, account, direction, reference)` and
`PhysicalProofOwner(producer, intent_id, observation_id, command_id)`, with
`PhysicalProofAuthority.lock/owners/claim`; retain these actual names and facts.
The prose names above describe semantics, not permission to replace the frozen
pure port with a parallel key/owner family. Same economic owner is the same
producer/intent; a new exact observation/command can retain its own identity
without reassigning that owner. Historical conflicting owners must remain visible.

Current P01 uses `payout-bank:` plus delimiter concatenation in
`payouts.bank_reference_lock`, and `receipt_used` checks settlements and paid
outcomes. `_result` takes the physical mutex before `_result_reason` and stores
actual outcomes outside the economic savepoint on refusal. Preserve that boundary
when inserting the shared claim, including failed economic application and
missing encryption/emergency gates. Claims must not disappear with the nested
money rollback. A physical conflict retains the newly observed evidence but
never replaces the earlier owner or applies money.

The new explicit source setting changes readiness as well as ownership:
`PayoutViewService._ordinary_actions` currently checks only the account before
advertising start. Task3 must add the same bounded missing/invalid configured
source denial to the writer and reader start capability (and its exact public
safe code allowlist), while keeping actual bank observation independently
available. Use read-only configuration facts; do not call a locking claim helper
from a snapshot. Extend focused read capability tests and relevant P01 carry.
Missing source does not silently map to a guessed provider. Existing historical
command hashes/receipts stay unchanged; synthetic positive tests explicitly
configure a synthetic source instead of weakening configuration requirements.

P01 service/repository/factory integration is NOT released while the accepted9h1
files are frozen for the pending9h2 actual-SQL/review preservation check. Root
coordinates that later cutover explicitly. Independent storage acceptance alone
does not grant Task3 source/PG. No code/database action occurred for this inventory.

### Task3a source/pure release and exact prerequisites

Root release,2026-10-24, after read-only feasibility review
`/tmp/umc-full-sprint-reports/task-6ca1-proof-plan-review.md`: Task3a may implement
only the DORMANT adapter and pure/config boundary. Exact file ownership:

- New `src/ugc_bot/infrastructure/db/repositories/physical_proofs.py`.
- `src/ugc_bot/config.py`: only optional `manual_bank_source_id`, alias
  `FINANCIAL_MANUAL_BANK_SOURCE_ID`, default blank, max256; no enablement/default
  provider or change to existing settings.
- `src/ugc_bot/application/physical_proof_ports.py`: only additive constant-text
  `PhysicalProofUnavailable(ValueError)` and `PhysicalProofConflict(ValueError)`
  plus protocol failure documentation. Their texts are respectively
  `physical_proof_unavailable` and `physical_proof_owner_conflict`; no IDs, bank
  data, arbitrary reason or exception text. Existing DTOs/validation/key/success
  signatures stay unchanged.
- New `tests/unit/test_physical_proof_authority.py` and
  `tests/unit/test_physical_source_config.py`; old shared fixtures stay frozen.

Economic owner equality is `(producer,intent_id)`; P01 intent is execution_id,
not request_id. Observation and command IDs retain actual provenance. Same-intent
reconciliation returns the original owner, never updates/reassigns the claim.
Historical multiple economic owners conflict even when one equals the caller.

Historical paid outcomes/settlements include successful-but-unapplied observations
and every recipient. Economic mismatch, stale state, missing key/emergency gate
must not filter out physical ownership. Map actual observed account, not merely
expected intent account. Exact historical command attribution uses immutable
receipt request/version to the matching bank_result event/outcome, or the actual
direct stored outcome_id. Require exact JSON types, action/actor/scope and one
unambiguous association. Missing/ambiguous historical association raises bounded
unavailable, never fabricates a UUID or returns unused/empty.

Use only identity.key canonical JSON for full-key comparison, hash and shared
transaction mutex. A persisted hash hit with different full components is
unavailable. `claim` locks/rechecks itself and inspects both claims and immutable
historical P01 before insertion. All methods require a real active caller SQL
transaction; no commit or standalone session is created. Constant failure types
preserve the outer transaction; unexpected database failure propagates normally.

New trusted command/outcome UUIDs may be preallocated for the same outer caller
transaction. The claim cannot require those not-yet-inserted references, and
must remain outside the money savepoint. Task3b will allocate command ID before
dispatch without adding it to the economic hash; final outer command/outcome/claim
commit or rollback stays atomic. Existing immutable claims validate their full
retained identity and IDs without inventing historical linkage. Newly arriving
actual observations never adopt a foreign owner.

Task3a is SOURCE/PURE ONLY: no PG module collection, engine, connection, schema,
migration, P01 producer/writer/reader/factory/error edit, existing shared test
fixture change, positive refund command, provider, flag, message, commit or deploy.
Pure tests can establish encoding, recognition, ownership classification and
historical row attribution from declared synthetic facts; they cannot prove SQL
locks, constraints, provenance queries or cutover. Keep every changed executable
module in honest sysmon measurement at98floor; report actual SQL-dependent
coverage as pending rather than mocking it into SQL acceptance.

Task3b remains separately unreleased until9h2 actual SQL and independent frozen
source preservation pass. It owns P01 integration/read hints/safe codes and real
pre-companion settled/unapplied history, shared-mutex races, expected-refusal
retention, outer rollback, same-intent reconcile and unchanged receipt/hash carry.
No Task3a result alone accepts the cutover or releases positive refund runtime.

### Task3a source/pure review accepted; SQL gate pending

The dormant five-file source/pure slice is frozen in
`/tmp/umc-full-sprint-reports/task-6ca1-proof-source-freeze.json`.
Builder report: `task-6ca1-proof-source-report.md`. Fresh pure/config carry is
127 passed, with Ruff/format on five files and mypy on three modules clean.
The unchanged 98% whole-module coverage gate is explicitly **FAILED** at
438/477 statements (91.82%); SQL lock/read/claim/recheck paths remain unexecuted.
No PostgreSQL work or P01 integration occurred. Thirteen other accepted Task2
hashes remain unchanged; the additive proof-port exceptions/docs amendment is
explicitly recorded rather than called unchanged. Fresh independent review
`task-6ca1-proof-source-independent-review.md` repeated all 127 tests, scoped
quality and coverage, verified five current and thirteen preserved Task2 hashes,
and found no Critical/Important source or pure issue. Root accepts this dormant
source/pure boundary only. Its unchanged 98% gate still FAILED at 91.82%; this
checkpoint grants no Task3b source/PG or positive refund runtime.

The former 9h2 preservation prerequisite has now been satisfied by independently
accepted 209 mandatory SQL tests and unchanged frozen source, as recorded in the
native-identity plan. A later Task3b release must still coordinate the actual
P01 source baseline, its reader/error/factory carry and the exclusive PG queue;
9h3 currently owns PostgreSQL. Those historical release restrictions were later superseded only by the exact
Task3b release and bounded independent acceptance recorded below.

### Task3 bounded source/SQL acceptance

Root read `task-6ca1-proof-cutover-independent-review.md` and its fresh
03:49:41UTC zero-resource PG release. Fresh773 passed in288.07s, exact1399/1412
=99.0793201%, eight pre-existing configured exclusions, quality17/8 clean and
all34 hashes preserved. Both common-mutex ownership orders had actual waits
across distinct backends;54 native carry cases completed. Portable exact old
producers established genuine pre-companion settled/unapplied history and the
actual parent-to-current upgrade without invented ownership. No Critical or
Important issue remained. Task3 is accepted only for common proof authority and
P01 cutover; positive refund runtime, forward guards, compensation, signed
ingress and fullAC9 remain open. Root coordinates Task4 source and PG separately.

## Task 4: Persist own requests, current-admin review, real observations and exact fresh matches

**Files:** Create `services/correction_service.py`; extend `repositories/corrections.py`; create `tests/postgres_financial/test_correction_commands.py`, `test_refund_observation_ordering.py`, `test_correction_evidence_retention.py`.

**Interfaces:** Implement `CorrectionService.execute` and own/admin reads from the shared contracts. Produce immutable approved intent bundles, observations and matches, with states `review_required`, `unmatched`, `matched_awaiting_assessment`, `application_review_required`, `applied` represented in separate review/match/application fields. `MatchSelectionRefund` calls the Task 6 compensation hook; until present it can persist a reviewed match awaiting assessment only.

- [ ] RED own/admin tests: actual current own client, explicit command choice, substantive reason; current active admin approval/evidence; foreign ownership, revoked/blocked admin, stale version/source/due and changed-payload key never apply. Same-operation replay returns byte-equivalent canonical original receipt while fresh status is separate. An ineligible own assigned/delivered request persists review-required evidence; it cannot receive a positive a1 intent.
- [ ] Freeze on approval: real original provider/account/external payment reference, capture event/payment/client, policy, quote/terms/due digest, original selection allocation keys and amounts/currency, absence/versions of assignment and delivery sources, and source-ground identities. Require current clock strictly after actual `selection_due_at`. Caller has no amount or recipient/ledger selectors.
- [ ] RED early observation test: issue real known invoice intent but withhold its actual payment receipt; record an admin-observed successful refund using actual configured physical source/account + original payment reference + known order/invoice intent. Persist nullable capture/payment/allocation references and owned proof. Unknown/mismatched/insufficiently correlated facts remain exception-only; they cannot silently select an unrelated order. An early case/intent carries no invented client request or approval. A later own-client request can attach to that same case after capture/due, followed by fresh current-admin approval/match.
- [ ] Deliver a later actual matching capture through `confirm_telegram_payment` at valid protocol time. Assert original capture/payment allocations are created normally and the observation is byte-for-byte unchanged. No match/application occurs automatically. New matching requires same logical intent/proof owner, original payment source/account/reference, current own request, fresh source/version review, exact captured bundle amount and currency. A new immutable match binds real sources; never fill old nullable columns by UPDATE.
- [ ] RED observation refusal tests: stale version, corrupt projection, partial amount, wrong currency, unsupported component/assignment/status and duplicate proof retain the actual manual observation plus specific unapplied reason. Successful facts remain true after later request rejection/case closure. Unauthenticated/non-admin or foreign own requests gain no privileged evidence writer.
- [ ] Persist observation and recognized proof claim in the outer caller transaction. Bound only match/application economics with repository savepoint; catch the explicit expected application-refusal class after rollback, persist the refusal result/receipt. Unknown programming/database failures abort the outer transaction; do not hide them as success. Corrupt state permits the standalone observation receipt with unavailable current state, no invented event transition.
- [ ] Run `uv run pytest tests/postgres_financial/test_correction_commands.py tests/postgres_financial/test_refund_observation_ordering.py tests/postgres_financial/test_correction_evidence_retention.py --require-financial-postgres -q`; observe meaningful RED then GREEN. At this checkpoint no cancellation is claimed applied merely because review/match succeeded.

## Task 5: Split gross capture authority from live funding and close every forward path

**Files:** Create `services/correction_funding_guard.py`; modify `entitlement_ports.py`, `repositories/{entitlements,selection_delivery_funding,paid_selection,paid_selection_delivery,item_assignments,payouts}.py`, `services/{client_entitlement_service,work_entitlement_service,payout_service,paid_selection_delivery}.py`, and the relevant factories. Create `tests/postgres_financial/test_correction_forward_guards.py`, `test_correction_lock_order.py`; extend existing paid-selection/work/payout runtime regressions.

**Interfaces:** `ClientEntitlementRepository.load_capture` explicitly remains immutable **gross** loading; it never calculates refund eligibility/net and never rejects a legitimate immutable capture because a sibling projection changed. Existing `ClientCapture/FundedSelection` retain original amounts. `CorrectionFundingGuard` owns live component net/unresolved state. `SqlAlchemyCorrectionRepository.discover_scope` also exposes the full prospective barrier set for existing producers. Later loads compare scope under held barriers: FORWARD commands and ordinary economic application refresh/retry on a new actor/source; an authenticated already-actual result follows the retention rule below instead of losing its evidence.

- [ ] RED tests: original capture still reloads after correction projection changes; zero/forged allocation/quote/capture source remains invalid. Gross amount/snapshots stay unchanged while `net_minor` only follows applied facts. Unknown/mismatched observations cannot reduce net. A sufficiently correlated pending early observation blocks affected order/item after capture but never unrelated orders/items.
- [ ] Use one gross validator in `entitlements.py`; make `selection_delivery_funding.py` delegate to it. Remove the live `selection_state not in ('refunded','cancelled')` policy test as monetary authority; validate original captured item identity from immutable sources and explicitly validate any mutable projection separately. Keep original price/currency/due/terms/capture/allocation integrity checks.
- [ ] Hook the same live guard at these actual boundaries, with tests for each: `paid_selection.confirm` before choosing/creating an initial assignment; `item_assignments.replace` before its initial-version write (existing low-level replacement seam is not permission to add a replacement producer); `paid_selection_delivery.lock_source/_current` reached by prepare, `_begin` and `_finish` after unlocked transport I/O; `ClientEntitlementService` before ordinary forward issuance; `WorkEntitlementService._assess/_issue` before creator/manager issuance, `_settle` before maturity recording and pending→hold/hold→available; `PayoutService._clear` for reserve, review/reject/start, settlement safety. Payout rejection must not release affected reserve while correction is unresolved. Keep current work/legacy/history/requirements/debt guards independently active.
- [ ] After root releases the completed9gb reader ownership, extend its `application/payout_view_ports.py`, `services/payout_view_service.py` and `repositories/payout_views.py` facts with the same correction-aware recipient/selected-allocation blockers and required source preflight. Exact reserve preview and admin action hints must stop promising readiness for scopes the new writer guard refuses; retain independent actual-observation capability and safe history. Do not call a locking/writing correction helper from RR, turn missing new sources into a zero, or edit in-progress9gb files concurrently. Include the reader in scoped P01/correction carry after integration.
- [ ] RED after-I/O test uses `test_paid_selection_delivery.py::Bot.hook` to record a correction while accepted transport is in flight. Preserve the actual accepted outcome with `applied=False`; no ACCEPTED fulfillment insert. Payout counterpart records correction between start and result; preserve bank outcome/proof, retain reserve and require later reconciliation, with no settlement/debt/release in a1.
- [ ] Discover **all** prospective users and wallets before any downstream lock: authenticated actor/reviewer, payer, creator/manager, current order managers, historical client and creator referral recipients, every existing item ground. Use sorted User locks, sorted `(user,currency)` wallets, current-role child barriers where applicable, then order/payment coordination, shared history barrier, sorted items, case/payout projections and the common proof mutex. Re-read sources/recipients after barriers. A newly discovered recipient causes whole-transaction refresh for FORWARD commands/economic application; no late User acquisition. For an authenticated already-actual result use the next retention rule. Re-entrant primitive locks on already-owned recipients are allowed, but must never introduce a new recipient after item/history locking.
- [ ] On an already-actual transport/bank result, a late economic source/recipient-set change is an expected application refusal, not an exception escaping before retention. Under the already held safe scope, retain the exact immutable observation and any recognized original physical-proof owner outside the economic savepoint, with applied=False/review-required. Do not acquire the newly discovered User/wallet, insert ACCEPTED fulfillment, settle/release/cancel/reserve/debt or reassign the proof. A later explicit reconciliation acquires a fresh complete scope. Current native-identity/admin failure still denies an untrusted actor before this path; ordinary database/outer commit failure remains atomic and is not swallowed.
- [ ] Add exact two-session REDs changing a manager/historical recipient between prospective discovery and final scope reread during `PaidSelectionDelivery._finish` and `RecordPayoutResult`. The existing delivery `_source` rethrows `selection_scope_changed_retry_required` before writing OUTCOMES: narrowly handle that expected finish-only case so its actual accepted provider receipt survives unapplied, while prepare/begin retain refresh behavior. P01 likewise must not let the expanded economic-scope reread escape before its trusted observation/proof retention. Assert distinct backend PIDs, original exact receipt/reference/intent, retained unapplied result/proof, no accepted fulfillment/settlement/release/debt, no late User acquisition and no automatic economic retry.
- [ ] RED independent-session races: correction vs interest/assignment; delivery finish; historical binding/role revocation; delayed consumer; payout review/start/result. Assert two actual backend PIDs, bounded completion/no deadlock, no late new User acquisition, retained evidence and no affected new money. Derive the payout's expanded prospective set **before** current `execute.lock_users`/`lock_money_scope`; checking a guard that discovers recipients after locking the item is insufficient.
- [ ] Run `uv run pytest tests/postgres_financial/test_correction_forward_guards.py tests/postgres_financial/test_correction_lock_order.py tests/postgres_financial/test_paid_selection_interest.py tests/postgres_financial/test_paid_selection_delivery.py tests/postgres_financial/test_work_entitlement_runtime.py tests/postgres_financial/test_payout_runtime.py --require-financial-postgres -q`; require RED then GREEN. The only special historical client path is the Task 6 transaction; do not add a caller-controlled bypass boolean.

## Task 6: Apply exact pending compensation and atomic delayed original assessment

**Files:** Create `services/client_refund_compensation.py`; modify `client_entitlement_service.py`, `repositories/corrections.py`, `repositories/entitlements.py`, and production factory wiring. Create `tests/postgres_financial/test_selection_refund_30255.py`, `test_client_refund_assessment_ordering.py`, `test_selection_refund_concurrency.py`, `test_correction_atomicity.py`.

**Interfaces:** Implement the internal compensation hooks defined above and `apply_match(match_id: UUID, *, actor_id: UUID, session: object) -> dict[str, object]`. Every application reloads the trusted reviewed match and actual obligations/potentials. No public API accepts this method's economic inputs. Return immutable application/assessment IDs, state and frozen component breakdown.

- [ ] First integration RED: use the actual 30-allocation fixture; call real `PaidSelectionInterestService.respond` for 25 distinct verified creators before due; run real `PaidSelectionDelivery` with synthetic receipt transport to create 25 immutable accepted delivery facts. Keep five positions with no assignment/delivery. After frozen due, own request those five, admin approve, record actual synthetic manual `250000` outgoing observation, fresh exact match. Consume client capture before refund for the first variant and after match for the second.
- [ ] Assert both orders yield original gross selection `1500000`, applied refund base `250000`, live net selection `1250000`; frozen 10% original client liability `150000`, remaining pending `125000`, cancelled `25000`; five linked `5000` pending reversals, same original per-item obligation/currency and actual issuance source-entry IDs; 25 original fulfillment facts and captured quote/allocation/payment snapshots unchanged. Assert client availability is not claimed; accompaniment contributes no percentage base. Reconcile the complete recipient journal/projection before and after.
- [ ] RED ordering variants: missing original assessment returns matched-awaiting-assessment and no applied refund-base/application fact. In `ClientEntitlementService.handle`, after complete scope locking/revalidation, `prepare_original_assessment` permits only fresh exact eligible matches. `_issue` establishes original gross obligations or covered no-recipient potentials once; `apply_matched_for_capture` completes **all** permitted cancellation lines; only then `save_receipt` writes the successful original assessment and the caller can consume the delivery. Force compensation failure after issuance: the consumer transaction must roll back issuance/potential, application/projection and successful consumer receipt together. The earlier observation/proof from its committed observation command remains.
- [ ] An already successful original receipt remains immutable and replay returns it; later match application appends its own correction facts. Never rewrite original assessment to a net basis or require another capture. If an existing receipt is absent while immutable grounds exist, reconcile their exact original keys/bases; do not create a second obligation or assume a receipt.
- [ ] RED known-absence variant: complete historical coverage with no effective referrer produces the existing durable `PotentialBasis` and a new immutable `financial_refund_liability_assessments` line referencing its actual `assessment_id`, original gross base, coverage/attribution proof and `liability_minor=0`; full physical/component application may then complete with no recipient, obligation or zero journal movement. Coverage missing/out-of-range/inconsistent stays unresolved, with no zero-liability line, applied correction or successful consumer receipt. Retain the existing historical-attribution validation.
- [ ] For each original client obligation, use its frozen base/rate/override/recipient/currency and actual issuance movement reference. Replay only validated same-ground/component/currency prior cancellation links; `target = commission_minor(B,r,RUB) - commission_minor(B-cumulative_refund,r,RUB)`; write only `target - prior_linked_cancelled`. Reject unexplained prior cancellation, source mismatch or negative delta. Zero delta creates a durable assessment/application breakdown with no zero journal. Do not recompute rate from current grade or registration state.
- [ ] Under the locked complete scope and application savepoint: validate exact whole bundle sum/currency and full selection amount for every line; enforce cumulative `[0, allocation.amount_minor]` across every case/proof; require only actual pending client liability, no creator/manager or nonpending affected liability. Reconcile before; append `JournalMovement(movement_type='reversal', bucket_from='pending', bucket_to='cancelled', refund_id=application_id, case_id=case_id, source_entry_id=actual_issue_entry_id, ...)`, apply projection, save component/application/assessment facts and validated resulting state, flush deferred checks, reconcile after. Canonical operation key is server-owned `refund:{match_id}:{obligation_id}:pending`. Never call lifecycle `transfer` for cancellation.
- [ ] RED refusal matrix: assigned/delivered/historical assignment; partial/mixed-component bundle; hold/available/blocked/reserved/executing/unknown/paid; accompaniment/management/replacement; arbitrary positive adjustment. Freeze actual evidence/case and affected blockers, with **no** positive application, debt, paid/reserve/available mutation, automatic release or subset of the physical bundle. A safe line cannot apply when another line is unsupported. A later rejection cannot unblock a successful observed refund.
- [ ] RED concurrency/corruption tests: same operation and two-admin/two-worker same match apply once; distinct proofs cannot over-refund an already exhausted component; first success unapplied still owns proof; forged cross-obligation/currency entry links and corrupted full-result state refuse. Force after-append/projection/deferred-check failures: application savepoint leaves no money/application writes while observation/proof/command-refusal receipt survives; force outer transaction failure: all facts from that command roll back. Catch only expected bounded refusals.
- [ ] Run `uv run pytest tests/postgres_financial/test_selection_refund_30255.py tests/postgres_financial/test_client_refund_assessment_ordering.py tests/postgres_financial/test_selection_refund_concurrency.py tests/postgres_financial/test_correction_atomicity.py tests/postgres_financial/test_client_entitlement_runtime.py tests/postgres_financial/test_client_entitlement_concurrency.py tests/postgres_financial/test_client_entitlement_security.py --require-financial-postgres -q`; require meaningful RED then GREEN. Original `FinancialEventRouter` keeps its existing caller transaction and producer registration; test routing/rollback rather than adding an asynchronous compensation consumer.

## Task 7: Wire strict signed ingress and finish bounded acceptance

**Files:** Create `miniapp/correction_api.py`, `miniapp/correction_wire.py`, `container/correction_factory.py`; modify `miniapp/api.py`, `container/{repository_factory,service_factory,payout_factory,paid_selection_delivery_factory}.py` only for released integration; create `tests/unit/test_correction_wire.py`, `test_miniapp_corrections.py`, `tests/postgres_financial/test_correction_api_postgres.py`; extend `tests/unit/test_financial_di.py` for graph checks.

**Interfaces:** `create_correction_router() -> APIRouter`; production dispatcher key `correction_service`; existing `transaction_manager`; factory `build_correction_service(config, transactions, session_factory)`. Reuse `SignedMiniAppRequest` and frozen9h1 existing-only configured-HMAC/freshness resolver/principal; never use auto-creating/default-country `_ensure_recent_user_and_get_id`. Revalidate current native mapping at the first complete sorted User barrier for commands and fresh reads, without an earlier actor-only lock. Money parser `parse_correction_minor(value: object, *, observed: bool) -> int | None` accepts canonical decimal **strings only** (or nullable observed absence), bounds before conversion, rejects JSON numbers/bools/floats/scientific notation/leading zeros/-0; recursive serializer renders every monetary field, including zeros and nested history, as strings.

- [ ] Write RED signed Telegram/MAX ASGI tests following `test_payout_api_postgres.py::{generate_init_data,router}` with real SQL/factory. Proposed routes under `/miniapp/api/financial/corrections`: `POST /request`, `POST /{case_id}/status`, `POST /admin/review`, `POST /admin/observations`, `POST /admin/match`, `POST /admin/{case_id}/history`, `POST /admin/exceptions`. Each mutation opens exactly one caller transaction. No browser/UI asset work.
- [ ] Assert forged/expired/wrong-platform/duplicate auth, query parameters, extra keys, `actor_id`, role/proof bool, foreign beneficiary/allocation/journal selectors and JSON numeric money are rejected; current own/admin SQL checks still apply under barriers. Responses and errors are no-store and validation failures never echo private submitted bank/evidence data. Own status/history excludes bank references and protected evidence; admin history uses current authority. No provider-verified or refund-paid claim based only on request/review.
- [ ] Actual signed TG/MAX unknown identities create no User; an existing MAX actor with missing country has no metadata write. In two actual sessions remap the native identity between initial resolver lookup and acquisition of the actor barrier: command/read must deny without returning the old actor's protected facts, appending a command receipt or changing money. Same canonical actor legitimately using its other current bound platform may replay the same unchanged economic command key; native auth metadata is not a new command payload.
- [ ] Keep original command result separate from freshly read state. Verify nested command receipt/application/component/observation money strings above JavaScript's safe integer range using unit transport fixtures, without creating an impossible captured component. Do not change P01's accepted historical command encoding or its prior payload hashes.
- [ ] Wire one configured proof authority and one live guard into SQL producers/consumers/factories; unit graph tests prove P01 and correction share it and every required hook is present. Missing production source/account configuration retains actual reports as exceptions and cannot enable positive application. No in-memory fallback in a SQL production graph may silently report clear.
- [ ] Run focused wire/auth/DI and the full new bounded PostgreSQL matrix with `--require-financial-postgres`; retain existing financial-router/outbox, client/work, paid-selection, P01 and legacy guard regressions. Then scoped `uv run ruff format --check <changed Python files>`, `uv run ruff check <changed Python files>`, `uv run mypy <changed source files>` and root-approved coverage over the real changed modules at 98%, with no omissions/threshold reductions. Root runs the final shared gate/migration isolation checks once all concurrent owners are stable.
- [ ] Prepare an implementation report listing exact RED/GREEN commands/results, actual migration parent/slot release, source hashes and fixture provenance, concurrency PIDs, retained-observation/savepoint/outer-rollback evidence, common proof cutover evidence and all remaining external/business boundaries. Obtain fresh independent review before declaring bounded a1 verified. Do not mark wider 6c, R05, P01, the 20-task/30-AC goal or external acceptance complete.

## Blocking facts and handoff checks

- **Execution prerequisite, not a design gap:** root must release stable P01 integration, the schema/PG slot and the real coordinated parent. No migration file or database inspection is authorized by this plan.
- **Production fact prerequisite:** positive matching needs the actual configured manual physical source/account and retained bank evidence. New optional configuration has no fabricated default; historical P01 labels without a recognized actual mapping stay exceptions. Synthetic test mappings prove software behavior only.
- **Per-case source prerequisite:** actual agreed selection due/terms/source coverage must be present. Existing immutable quote/intake sources can supply it; absent historical agreement evidence does not become an invented deadline. Complete referral history can prove known absence; unavailable coverage cannot.
- The post-delivery refund duration anchor is still unanswered and unnecessary for this unfulfilled-selection path. Client close/maturity, positive nonpending/reserved/paid corrections, repayment, replacement/work resolution, accompaniment arithmetic, manual positive adjustment and UI remain explicit follow-ons.
- Self-review: all approved a1 requirements map to Tasks 1–7; Review Focus items have owning RED scenarios; referenced commands/types/hooks are defined above; source links use actual text allocation keys and actual ledger movement UUIDs; no test asserts client availability, assumes a future migration parent or manufactures historical proof ownership. Planning did not run tests or inspect PostgreSQL, and records no implementation acceptance.
