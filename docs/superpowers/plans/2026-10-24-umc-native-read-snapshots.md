# UMC native identity in private read snapshots implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans after root separately releases source. Steps use checkbox tracking. This plan grants no implementation or PostgreSQL access.

**Goal:** Validate the signed Telegram/MAX mapping inside the same coherent snapshot as each private partner, own-selection and campaign-summary response.

**Architecture:** Forward the existing immutable `AuthenticatedMessengerPrincipal` through explicit optional internal keywords. Each actual SQL adapter checks fresh native columns at its first User query after starting REPEATABLE READ READ ONLY, before reading private facts. HTTP requires typed existing-only proof; trusted internal callers retain their current explicit compatibility.

**Tech Stack:** Existing Python 3.13, FastAPI, SQLAlchemy async PostgreSQL, pytest/sysmon and current signed TG/MAX request helpers.

**Spec:** Task3 of `2026-10-24-umc-native-identity-fences.md`, the private-history/ownership requirements in `docs/product/UMC-developer-sprint-2026-10-22.html`, and the read-only addendum in `/tmp/umc-full-sprint-reports/task-9h3-source-map.md`. This follows the separately released intake/collaboration slice; it does not accept that slice's pending SQL evidence.

## Global constraints

- Work only in `/home/bulat/.codex/worktrees/umc-full-sprint/ugc`; primary user files remain untouched.
- Cover exactly partner `/view`, own order `/selection`, and order `/campaign-summary`. Campaign commands/settings/drafts, social editing and other legacy routes remain separate follow-ups.
- No global resolver replacement, new migration, account creation, MAX country fill, wallet initialization, financial command/hash change or response-economic reinterpretation.
- Proof validation and all private facts use the same RR READ ONLY transaction. No row/advisory/User/wallet/item locks, writes, autoflush or writer helper is introduced.
- Current status, advertiser role, own client/current manager membership, safe pagination, historical money and financial-versus-legacy summary semantics remain authoritative.
- Require typed server proof on HTTP; the optional internal keyword is never a body field or an HTTP fallback. Missing mapping or a mismatched canonical UUID denies before private reads/output.
- Preserve no-store responses and constant validation/unexpected errors with exact safe public codes. Raw submitted auth, body values and arbitrary exception detail never enter error responses or logs.
- Keep the unchanged 98% coverage floor. No live account/provider/Redis/message, production DB, flags, commit, push or deployment.

## Review focus

1. A remap committed after gateway lookup but before the snapshot's first SELECT must deny without reading the old account's private network/history/order data (Tasks1–3).
2. A remap committed after the first snapshot SELECT must not mix current native facts with older private sources; return one coherent prior snapshot or a bounded refusal, never add a writer lock (Tasks1–3).
3. A missing or UUID-only HTTP proof must not take the trusted internal compatibility path, create a User or populate MAX country (Tasks1–3).
4. Paused/blocked/deleted actors, revoked advertiser/manager membership and foreign order IDs retain each existing route's authorization semantics (Tasks1–3).
5. Validation, context resolution, source failure and response encoding all remain within a no-store constant-error boundary; token/private values cannot leak through a default422 or arbitrary PermissionError (Tasks1–3).

## File map and ownership

Modify only these existing snapshot families:

- `application/partner_view_ports.py`, `services/partner_view_service.py`, `infrastructure/db/repositories/partner_view.py`, `miniapp/partner_api.py`.
- `application/selection_view_ports.py`, `services/selection_view_service.py`, `infrastructure/db/repositories/selection_view.py`, `miniapp/selection_api.py`.
- `application/campaign_summary_ports.py`, `services/campaign_summary_service.py`, `infrastructure/db/repositories/campaign_summary.py`, `miniapp/campaign_summary_api.py`.

After the active9h3 owner freezes `miniapp/native_caller_errors.py`, additive route subclasses may reuse `_NativeCallerRoute` in that same module: `NoStorePartnerRoute`, `NoStoreSelectionRoute`, `NoStoreSummaryRoute`, with exact route-specific maps/prefixes. Do not alter intake/collaboration behavior or refactor the frozen payout boundary. Root owns THREE central resolver injections in `miniapp/api.py`.

Create `tests/unit/test_native_snapshot_api.py` and `tests/application/services/test_native_snapshot_views.py`; extend only corresponding existing pure fakes/expectations. Create `tests/postgres_financial/test_native_snapshot_views_pg.py` in the later separately authorized SQL phase. Carry existing partner/selection/summary tests rather than replacing their assertions.

## Task1: Typed gateway and explicit snapshot proof contract

**Interfaces:** Add `principal: AuthenticatedMessengerPrincipal | None = None` to `PartnerViewService.view` and `PartnerViewRepository.read`, preserving the current caller-owned `session`. Add the same keyword to `SelectionViewService.view` / `SelectionViewRepository.view` and `CampaignSummaryService.view` / `CampaignSummaryRepository.view`, preserving their own existing transaction and begin_snapshot calls. Existing positional actor/order IDs and response structures stay unchanged. The SQL adapter consumes the proof inside its snapshot; it is not appended to returned public facts.

- [x] Add `test_snapshot_http_requires_typed_native_proof`, `test_snapshot_http_uses_principal_uuid_only`, `test_snapshot_principal_is_not_public_data`, and `test_snapshot_internal_calls_keep_explicit_compatibility`. Parameterize all three routes and TG/MAX. Assert UUID/None proof never calls the view, body actor/recipient overrides are rejected, no User/country/wallet write occurs, and missing proof is not silently converted to an internal call.
- [x] Run `.venv/bin/python -m pytest tests/unit/test_native_snapshot_api.py tests/application/services/test_native_snapshot_views.py -q --no-cov --tb=short`; first capture behavioral RED, not an unrelated import/environment failure.
- [x] Forward the typed proof explicitly from each gateway, derive actor UUID only from it, and validate proof/actor consistency before entering private work. The adapters' fresh snapshot checks use the accepted pure `require_current_principal` helper. No native metadata enters public/economic DTOs or hashes.
- [x] Add the three additive no-store route classes and exact safe error maps. Entire route handling, context/service lookup, query/body validation and response encoding must be covered. Preserve expected route-specific403/404/503 semantics; unexpected detail becomes a constant route unavailable code.
- [x] Run new pure/API tests plus `test_partner_view_service.py`, `test_partner_api_availability.py`, `test_selection_view_unavailable.py`, `test_partner_referral_config.py` and relevant actual-app pure carry. Root applies exactly three resolver injections only after typed routers are ready. Run scoped Ruff/mypy; report source checkpoint with no SQL claim.

## Task2: Compare native identity at the first snapshot actor query

**Interfaces:** Actual repositories retain current signatures plus Task1's optional principal keyword. `partner_view.read` starts its existing RR READ ONLY transaction then selects actor UUID/status/referral_code/native columns. `selection_view.view` selects current actor UUID/status/native columns after service.begin_snapshot. `campaign_summary.view` changes its status-only query into the same bounded UUID/status/native projection after begin_snapshot. Each validates the supplied proof immediately, before network/history/role/order/private source queries. Native columns stay internal.

- [x] Add `test_snapshot_native_mismatch_denies_before_private_reads`, `test_snapshot_actor_uuid_mismatch_denies`, `test_snapshot_native_missing_denies`, `test_snapshot_check_precedes_private_sources`, and `test_snapshot_status_and_membership_semantics_preserved`. Synthetic boundaries in pure tests are explicitly declared; they do not prove actual MVCC. Include all three families, both platforms and missing actor.
- [x] Capture RED for those cases. Implement the minimal selected-column comparison in each actual adapter, preserving its existing first-SELECT snapshot boundary. Do not acquire a writer lock, refresh through a different connection, restart a snapshot, perform a registration fallback or read private facts before proof validation.
- [x] Preserve partner pages/standards/payment snapshots and the selection accepted-history rules. Preserve summary's own-client/current-manager scoping and both financial and legacy aggregation families. Existing missing/unavailable sources remain distinct from zero.
- [x] Run the new pure/API and relevant existing carry GREEN, then quality. Measure every changed executable module honestly with sysmon and explicit whole-file scope at98%; report any failed coverage as pending rather than excluding legacy branches. Freeze sources and report to root; no SQL collection before the separate grant.

### Accepted bounded source/pure checkpoint; SQL and 98% still pending

Root read `/tmp/umc-full-sprint-reports/task-9h4-source-independent-review.md`:
no Critical/Important source or pure finding; fresh602 tests in2.98s with no
skips/deselections; scoped quality20 passed and all20 current hashes matched.
Historical intake/collaboration wrapper bytes remain exact; root's three
resolver argument changes are the only intentional central API delta.
Whole14-module sysmon754/1736=43.4331797%, zero exclusions, FAILED the unchanged
98 floor; owned13 is385/553=69.6202532%. These failures remain pending actual
SQL and broad carry and are not waived by source readiness. No actual PostgreSQL
or MVCC evidence occurred. The independent source freeze remains authoritative
for the next phase. Root's main plan records any preparation or PG handoff.

## Task3: Actual signed ASGI and two-session MVCC evidence

**Files:** New PG test file plus owned source/tests above. No migration. Reuse current private UUID-schema fixtures, actual repositories/services and signed TG/MAX helper patterns from existing partner/selection/summary API tests.

- [x] After root's explicit PG grant, write ordinary mapping-first and snapshot-first tests for each family and TG/MAX. Record two distinct actual backend PIDs and use deterministic barriers around the first actor SELECT. PID/settings instrumentation must not issue an earlier SELECT that establishes the RR snapshot: obtain PID from established driver metadata or capture it at the actor query, and inspect settings only after the controlled snapshot boundary. Mapping-first must deny before any private-source query. Snapshot-first may complete against its coherent old mapping and private facts while the remap commits independently; no lock or mixed-current reread is allowed.
- [x] Assert actual transaction isolation/read-only settings and captured SQL show no User/wallet/item/advisory lock, DML, wallet creation or metadata write. Include missing native binding/account, foreign IDs, status and role/membership changes, and MAX without country. Actual signed unknown identity never registers a User.
- [x] Run `.venv/bin/python -m pytest tests/postgres_financial/test_native_snapshot_views_pg.py tests/postgres_financial/test_partner_view_api.py tests/postgres_financial/test_selection_view_api.py tests/postgres_financial/test_campaign_summary.py --require-financial-postgres --no-cov -q --tb=short`; require exit0 with no skips and completed distinct-PID cases. Do not sum overlapping carry/targeted reruns.
- [x] Complete the real changed-module sysmon98% gate, scoped quality and source freeze. Dispose engines, verify zero private schemas/other sessions/owned processes and explicitly release PG. Root obtains independent source/SQL review and later a stable whole-tree gate. Campaign/social/legacy callers, device QA and full sprint remain open.

### Accepted bounded actual source/SQL checkpoint

Root read `task-9h4-sql-independent-review.md` and fresh04:10:15UTC
zero-resource release. Independent1365 tests passed in71.51s, no skips;
whole14-runtime1708/1736=98.3870968%, helper193/195 and inclusive1901/1931,
zero exclusions.52 distinct-PID reader/writer cases completed with no wait
claim. Source20 and prepared2 stayed unchanged; quality22 and all66 repository
plus18 evidence references matched. No Critical/Important issue remained.
This accepts only the three private read snapshots and explicit carry; broader
native callers, real-device QA, whole-tree gate and full sprint remain open.

## Historical planning boundary and self-review

At plan creation, no implementation, PG operation or test run occurred while writing it. Source release waits for the active9h3 error wrapper and ownership to freeze and for independent feasibility review; PostgreSQL requires its own exclusive handoff. Current migration head confers no DB access.

All five review-focus conditions have named owning tests. Signatures preserve existing session ownership and optional trusted internal behavior without an HTTP fallback. The design compares native authority inside each established snapshot rather than importing a financial writer barrier. No new business rule, public field, metric interpretation, provider or legal fact is introduced.
