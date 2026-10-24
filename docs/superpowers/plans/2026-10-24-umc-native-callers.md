# UMC intake and collaboration native-principal implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans after root releases this bounded source phase. Steps use checkbox tracking. This document is plan only; root separately grants source and exclusive PG access.

**Goal:** Keep the signed Telegram/MAX caller bound to the same current canonical account during order intake and public collaboration reads/commands.

**Architecture:** Reuse the accepted immutable `AuthenticatedMessengerPrincipal` and existing-only financial resolver, outside economic command hashes. Intake checks fresh native fields at its existing client User barrier. Public collaboration gets a bounded preparation step that locks the complete prospective User set before the existing item barrier, then reuses the existing lifecycle and capability methods in one caller transaction.

**Tech Stack:** Existing Python 3.13, FastAPI/Pydantic, SQLAlchemy async PostgreSQL, pytest/sysmon and signed TG/MAX requests.

**Spec:** Task3 of `2026-10-24-umc-native-identity-fences.md`, the sprint's ownership/private-history requirements in `docs/product/UMC-developer-sprint-2026-10-22.html`, and `/tmp/umc-full-sprint-reports/task-9h3-source-map.md`. The original 9h1 bounded review is accepted; its source/helpers remain frozen.

## Global constraints

- Work only in `/home/bulat/.codex/worktrees/umc-full-sprint/ugc`; do not touch the dirty primary checkout.
- This first caller slice covers exactly the two intake and two collaboration HTTP paths. Partner, selection, summary, campaign and social contexts remain explicitly queued follow-ups.
- No global generic UUID resolver replacement, ambient authentication state, account creation/country update, schema/migration, financial formula or saved payload-hash change.
- HTTP bodies cannot choose native identity/actor/role or trusted system producers. Every HTTP path must require a real typed server principal.
- Existing current role/status, paid scope, dispute, deadline, replay and membership checks remain authoritative after native validation.
- All prospective User locks precede role/history/item/record/event locks. No actor-only preliminary gateway lock and no newly discovered User after the item barrier.
- Trusted internal scheduler/notice producers retain their existing item-serialized contract and do not acquire late User locks through the new public wrapper.
- Use exact safe error codes, constant unexpected/validation errors and no-store responses. Do not echo body/auth/private exception text.
- New tests use synthetic adapters/private PG only. No live accounts, messages, provider operations, flags, commit, push or deployment. Keep the unchanged 98% coverage floor.

## Review focus

1. Native binding changes between gateway resolution and the service barrier: deny before private policy/work output, old receipt replay or event/order creation (Tasks1/2/3).
2. Collaboration scope changes during preparation, or public actor differs from recipient/other parties: use the complete sorted current set or refuse/retry the whole transaction; never add a late User (Tasks2/3).
3. HTTP status/command then capability assessment shares an item-locked transaction: do not begin a second User-preparation cycle after the item lock (Tasks2/3).
4. Scheduler or actual notice-result processing already holds item/outcome scope: preserve its existing no-public-principal path and evidence retention (Tasks2/3).
5. Existing-only resolution encounters a missing account or missing MAX country: return the normal bounded denial/unpublished outcome, without registering a User or filling country (Tasks1/3).

## File map

Modify intake only: `domain/order_intake.py` (`IntakeClient` authority facts only), `application/services/order_intake_service.py`, `infrastructure/db/repositories/order_intake.py`, `miniapp/order_intake_api.py`. Preserve `OrderIntakeCommand` and its hash.

Modify collaboration only: `application/collaboration_ports.py`, `application/services/collaboration_service.py`, `infrastructure/db/repositories/collaborations.py`, `miniapp/collaboration_api.py`. Add focused public orchestration methods; preserve economic `CollaborationCommand` and all trusted system fields/hash.

Root owns the two explicit resolver injections in `miniapp/api.py`. A small new `miniapp/native_caller_errors.py` may centralize constant/no-store validation and exact public code mapping for these two routers; it must not refactor the frozen payout route wrapper or unrelated routers.

Create `tests/unit/test_native_caller_api.py`, `tests/application/services/test_native_intake.py`, `tests/application/services/test_native_collaboration.py`, `tests/postgres_financial/test_native_caller_fences_pg.py`. Extend only the existing intake/collaboration memory fakes that implement newly required authority/preparation facts. Changes to old expectations must document the intentional existing-only/native validation compatibility change; do not weaken assertions.

## Task1: Existing intake barrier and strict signed gateway

**Interfaces:** `OrderIntakeService.eligible_policies(client_id: UUID, *, principal: AuthenticatedMessengerPrincipal | None = None)` and `create(command: OrderIntakeCommand, *, principal: AuthenticatedMessengerPrincipal | None = None)` preserve trusted internal calls. `IntakeClient` gains optional native fields with explicit compatibility defaults; the actual SQL `lock_client` returns fresh `telegram_id` and `max_id` from its existing locked User row.

- [x] Write RED cases `test_intake_native_bound_actor_succeeds`, `test_intake_changed_binding_denies_policy_and_replay`, `test_intake_uuid_mismatch_and_missing_mapping_deny_without_order`, `test_intake_current_role_status_still_deny`, `test_intake_unknown_actor_creates_nothing`, and `test_intake_auth_is_not_command_hash`. Parameterize TG/MAX, check orders/quote/lead/receipt facts remain unchanged on denial, retain successful same-owner cross-platform replay.
- [x] Run the three new pure files with `-q --no-cov`; initially select intake tests. Expected RED is absent proof handling/behavior, not a broken import environment.
- [x] Check `require_current_principal` immediately after the existing complete client barrier before permission/replay/private policies and order/lead writes. Keep lock strength/order unchanged and the principal outside economic dataclasses. Require typed resolver results on both HTTP paths and use only the accepted existing-only resolver.
- [x] Add exact normal public code maps and no-store behavior for expected HTTP/domain denials, constant unexpected and 422 responses; preserve valid existing status semantics. Reject missing/UUID-only HTTP proof. Unknown private text never becomes a public error. No token logging.
- [x] Run intake plus relevant existing policy/intake service/API carry GREEN and scoped Ruff/mypy. Existing memory callers without public principal retain explicitly trusted behavior; no HTTP missing-proof bypass.

## Task2: Public collaboration preparation and single orchestration

**Interfaces:** Add immutable `CollaborationPrincipalScope` to collaboration ports containing the exact discovered `(assignment_id, paid_item_id, order_id, client_id, creator_id, manager_id)` source tuple, actor ID and sorted prospective User IDs. `CollaborationRepository.prepare_principal_scope(assignment_id: UUID, actor_id: UUID, principal: AuthenticatedMessengerPrincipal, *, session: object) -> CollaborationPrincipalScope | None` is a transaction-bound preparation operation. SQL discovers only minimal assignment/item/order ownership facts, locks actor/client/creator/optional manager Users in UUID order using existing User barrier strength, validates fresh native proof, then locks the frozen discovered item and reloads/verifies the complete exact source tuple. A changed item/order or swapped party role must refuse even when the distinct User-ID set is unchanged. Missing assignment validates the known actor scope before returning `None` without falling through to a newly appeared assignment. Changed scope refuses the whole transaction; it never locks an extra User later.

Public service interfaces are `get_authenticated(assignment_id, principal, *, session) -> tuple[CollaborationRecord, bool, tuple[str, ...]] | None` and `execute_authenticated(command, principal, *, session) -> tuple[CollaborationRecord, bool, tuple[str, ...]]`. They prepare exactly once before invoking existing get/execute/actions in that same caller transaction. Thread the exact prepared tuple explicitly through bounded private orchestration into every reentrant scope load: compare the discovered item with the prepared item BEFORE choosing a lock, lock only that prepared item, then compare the full tuple after the wait. No reentrant call may silently rediscover and lock a different item or accept same-User-set role/order changes. Existing trusted calls keep their no-preparation contract. The prepared value stays local to that orchestration, cannot be supplied by HTTP or persisted. If threaded as a repository argument, bind it to the actual caller session and active root transaction, and reject reuse after commit/rollback or in another session before scope reads/locks. It must not become a session-lifetime capability. An optional expected-scope argument on the bounded private bodies/repository is acceptable; no ContextVar or ambient principal is introduced. Existing trusted `execute/get_for_actor/actions_for_actor` remain supported and acquire no new late User through their internal system paths.

- [x] Write RED cases `test_work_current_native_scope_succeeds`, `test_work_changed_binding_denies_status_command_and_replay`, `test_work_complete_sorted_user_scope_precedes_item`, `test_work_changed_party_set_refuses_without_late_user`, `test_work_same_users_changed_source_tuple_refuses`, `test_work_reentrant_scope_never_locks_a_changed_item`, `test_work_capabilities_reuse_prepared_transaction`, `test_work_missing_assignment_checks_actor_then_returns_absent`, and `test_work_system_notice_and_sweep_keep_existing_contract`. Include actor UUID before/after other parties, distinct admin/recipient, no manager, current revoked membership, invalid public system fields and unexpected scope change. Check no event/outbox/private response/receipt changes on denied proof.
- [x] Run the selected collaboration/API cases RED. Inspect actual SQL FK targets on collaboration/event/notices so all prospective User references are included before item writes; a public actor alone is not the complete write set.
- [x] Implement the typed bounded preparation and two public orchestration methods. Fresh User/native facts must use selected columns or explicit population. Revalidate the actual item scope after waiting; no preliminary actor lock and no late User. Preserve current role/status/resource authorization and original command hashes/receipts. System notice/sweep methods keep their current producer checks and actual-result semantics.
- [x] Wire the two HTTP paths to the public orchestration methods with mandatory typed principal; do not call another public preparation when formatting capabilities in the already item-locked transaction. Reuse Task1's constant/no-store error boundary with an exact collaboration allowlist.
- [x] Run new collaboration/API tests and relevant old collaboration/sweep/notice pure carry GREEN; scoped quality. Report source freeze to root; do not open PG without the separate grant.

## Task3: Real two-session behavior and bounded acceptance

**Files:** new PG test file plus owned runtime/tests above. No migration. Reuse actual intake/collaboration fixtures and current private migration head; do not synthesize production capture/assignment authority outside the existing fixture producers.

- [x] After explicit PG release, add normal-behavior mapping-first and authorization-first TG/MAX cases for intake policies/create/replay and collaboration status/command/replay/capability composition. Distinct real PIDs, actual wait evidence and bounded completion are required. Capture emitted User ordering/strength and ensure no User acquisition after the first item lock.
- [x] Test missing/native-remapped/cleared canonical mapping, current role/status revocation, same-canonical TG→MAX receipt stability, complete actor/party scope, changed source set, and no implicit country/User creation. Test actual notice outcome retention and sweep carry without a public principal. Do not claim an untested race from a source read.
- [x] Run `tests/postgres_financial/test_native_caller_fences_pg.py` with mandatory private PG and the existing intake/collaboration API/persistence/notice/sweep carry. Expected GREEN is exit0, no skipped bounded cases, all recorded reader/writer PIDs distinct/completed and actual source invariants unchanged. Redact DSNs and private inputs from saved logs.
- [x] Run a fresh scoped sysmon gate with all changed executable runtime files honestly attributed, unchanged98floor, no omit/exclusion workaround. Report pure/PG counts separately from overlapping reruns. Run quality on owned modules and root's central injection.
- [x] Freeze sources; explicitly dispose engines and verify zero private schemas, other client sessions and owned processes. Root obtains a fresh independent source/SQL review and later stable whole-tree gate. No broader caller, device or full-sprint acceptance follows automatically.

## Execution and completion boundary

Root bounded acceptance, 2026-10-24: Tasks1–3 are accepted after
`/tmp/umc-full-sprint-reports/task-9h3-sql-independent-review.md` found no
Critical/Important issue and independently repeated919 tests (125new PG,
96existing PG,698pure/API), zero skips, exact2160/2187 statements=98.765432%.
Fresh70 actual waits and72 distinct PID pairs passed;17current plus10+3+23
preservation entries matched before/after. Scoped quality passed. The independent
PG owner verified zero sessions/private schemas/owned processes and disposed its
engine at02:58:34UTC, then explicitly released the slot. Original source and
status-fix reports, earlier failed/rounded gates and all historical freezes remain
separately preserved. This accepts only the bounded intake/collaboration slice;
partner/selection/summary/campaign/social callers and the stable whole-tree/full
sprint gate remain open. Original source/PG releases described earlier are
historical; the current root handoff is recorded in the main sprint plan.

Root's current static migration head is `financial_corrections_a1`, parent `campaign_drafts_v1`; recheck that coordinated head before any later PG grant. This plan adds no migration and must not claim a database slot from a visible head. Preserve the frozen9h1 helper contracts and accepted9gb read snapshot. Partner/selection/summary/campaign/social caller completion remains queued with its own source design; no ambient/global resolver change is authorized.

Self-review: each focus condition has an owning target test; source ownership, caller/session ownership and internal/public method distinction are explicit. Missing scope and changed scope cannot trigger a new late User lock; no bank/provider/legal decision is introduced. No source/test/PG operation was performed while writing this plan.
