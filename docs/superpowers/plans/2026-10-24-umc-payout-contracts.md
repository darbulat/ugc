# UMC payout contracts Stage 9g-a implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task after root GO. Steps use checkbox tracking. The execution method is inline in the existing shared worktree; do not spawn workers, commit, or start a database run during the current freeze.

**Goal:** Make the P01 boundary exact and recoverable: string money, immutable readable publication and explicit acceptance, own safe operation lookup, and masked own requisites.

**Architecture:** Keep money and retained command facts unchanged in domain/SQL; adapt presentation at the API edge. Add immutable companion documents/publication bindings/acceptances after `campaign_digest_v1`, with no mutation of frozen P01 tables. Reuse the actual User command barrier for own recovery; leave financial readiness and immutable state-authority checks in force.

**Tech stack:** Existing Python 3.13, FastAPI/Pydantic, SQLAlchemy/PostgreSQL/Alembic, signed Telegram/MAX ingress, configured AES-GCM adapter, pytest/sysmon coverage.

**Spec:** `docs/superpowers/briefs/umc-full-sprint/task-9g-payout-ui.md`, including “Stage9g-a implementation clarifications”; P01 implementation and P1 fix reports in `/tmp/umc-full-sprint-reports/`.

## Global constraints

- The preparation freeze ended with explicit root GO. Implementation ran inline in the existing shared worktree with the exclusive PG slot; root still serializes independent review/shared gates.
- Stage 9g-a excludes context/capabilities/paging (9g-b), browser screens/storage/native controls (9g-c), refunds/debt recovery (6c), provider calls, legal drafting, activation and commits/push.
- Domain/SQL minor amounts stay integers; `MAX_MINOR = 9223372036854775807`. No floating point, rounding, reduced product maximum, invented minimum, tax or fee.
- Preserve old command hashes/results, ciphertext, opaque historical publications and all journal/state/event facts. No opaque document can authorize a **new** acceptance or new owner reserve.
- Current P1 history readiness, current-role/ownership checks, full immutable projection authority and retained/unapplied bank evidence remain unchanged.
- Publication text is actual admin input; source language and exact text/hash are retained. No generated/translated legal text or invented URL. Disabled publication requires no invented document.
- Reads/recovery remain possible during pause/key loss under current owner policy; recovery never claims that an absent receipt prevents a delayed original request arriving later.

## Review focus

1. An old cached integer receipt is returned through the new string wire without modifying its stored hash or making a new movement — Task 1/3.
2. Optional DTO defaults change `asdict()` and break old publication/requisites hashes — Task 3 must omit only whitelisted unused new fields.
3. A status lookup started before an in-flight commit returns false absence — Task 4 uses the same User barrier and a fresh post-wait READ COMMITTED lookup.
4. Missing companion tables or opaque terms accidentally become a fixture-only acceptance bypass — Task 2/3/5 distinguish old-schema readability from new acceptance.
5. Lost admin authority, key loss or poisoned retained JSON exposes private values through recovery/masked reads — Task 4 uses an explicit owner-action/result whitelist and metadata-only responses.

## Files and stable interfaces

Create:

- `src/ugc_bot/miniapp/payout_wire.py`: `parse_minor(value: object, *, observed: bool) -> int | None`; `payout_to_wire(value: object) -> object`.
- `src/ugc_bot/application/payout_contract_ports.py`: frozen document input/reference, field-definition and acceptance-proof DTOs; typed safe recovery/read results.
- `src/ugc_bot/application/payout_contracts.py`: publication/schema/acceptance validation and legacy-compatible command-payload projection.
- `src/ugc_bot/infrastructure/db/payout_contract_schema.py`, `payout_contract_models.py`, `repositories/payout_contracts.py`: companion DDL/registration and transaction-bound persistence; no edits to frozen `payout_schema.py`.
- `src/ugc_bot/infrastructure/db/migrations/versions/financial_payout_contracts_v1.py`: child of `campaign_digest_v1`; announce/confirm head with root **after GO**, before creating it.
- `tests/unit/test_payout_wire.py`, `tests/unit/test_payout_command_compatibility.py`; `tests/postgres_financial/test_payout_contracts.py`, `test_payout_recovery.py`, `test_payout_contract_migration.py`.

Modify narrowly:

- `application/payout_ports.py`: optional new publication/acceptance fields; old fields/default meanings unchanged.
- `application/services/payout_service.py`: payload projection before hashing; publication/store/new-reserve binding checks; `operation_for_actor(actor_id, operation_key, *, session)` and `requisites_for_actor(actor_id, *, session)`.
- `infrastructure/db/repositories/payouts.py`: compose the companion repository; keep existing barrier, state/history authority and money primitives unchanged.
- `miniapp/payout_api.py`: exact wire models/replies; signed POST `/operations/status` and `/requisites/list` before dynamic UUID route. Central metadata hook is a narrow root-coordinated import only.
- `tests/postgres_financial/test_payout_runtime.py` and payout API/defensive/history tests: upgrade positive fixtures to actual synthetic readable publication/acceptance. Preserve exact old-revision tests as below.
- `tests/helpers/financial_environment.py`: only if needed, add `upgrade_financial_schema(engine, *, target_revision)` using the same isolated-schema Alembic subprocess convention and actual revision chain; never drop descendants/history or print URLs.

## Task 1 — Exact monetary wire; no stored-data change

**Contract:** Responses recursively stringify monetary integer fields (`amount_minor` and named `*_minor` money fields), including arrays, nested history, outcomes, event details and retained command results. Null stays null; versions, booleans, ordinals and timestamps are not money. Raw private string maps are not interpreted as numbers. Serialize on a copied response after the transaction, never into saved command JSON.

Inputs accept existing strict JSON integers for compatibility and canonical ASCII strings. Reserve grammar is `[1-9][0-9]*`, range `1..MAX_MINOR`. Observed amount grammar is `0|-?[1-9][0-9]*`, range `-MAX_MINOR..MAX_MINOR`, or null. Reject bool, floats, exponent, whitespace, plus, leading zero, `-0`, non-ASCII digits and overflow. Convert to int **before** constructing/hashing domain commands. Do not broaden accepted observation ranges or clamp exceptions.

- [x] Write unit RED: `test_minor_wire_preserves_53_bit_and_bigint_boundaries`, `test_observed_signed_zero_null_and_invalid_grammar`, `test_nested_money_copy_leaves_versions_and_original_receipt_unchanged`.
- [x] First RED command: `.venv/bin/python -m pytest -q tests/unit/test_payout_wire.py`.
- [x] Implement `payout_wire.py`; use its parsers in `Reserve`/`BankResult` and its recursive serializer in every P01 reply, including lookup. Keep domain commands/result storage as int.
- [x] Run unit GREEN, then actual signed TG/MAX cases: existing available 60,000 rejects a MAX reserve as insufficient without rounding; prepared real 60,000 execution records MAX, `-MAX`, zero and null observations unapplied and returns the exact strings in nested protected history. No fictitious MAX balance/payment is seeded.
- [x] Assert the actual response JSON has strings at every monetary path; assert unchanged persisted integer outcomes/command JSON. Representative mapper unit fixtures cover MAX request/list/result paths unreachable with the small real paid fixture.

## Task 2 — Companion schema and readable publication

**Companion facts (append-only, NO ACTION references, no plaintext requisites):**

1. `financial_payout_terms_documents`: document ID, exact content text, source locale, server SHA-256 of exact UTF-8 bytes, actual publisher/time. Reuse an existing actual document by ID without relabeling its original publisher/time.
2. `financial_payout_requirement_contracts`: requirements ID PK, actual document ID/hash, exact field definitions bound to that publication. Composite unique scope supports acceptance FK. No binding is backfilled onto an old opaque publication.
3. `financial_payout_requisites_acceptances`: existing requisites/recipient/requirements composite scope, document ID/hash, explicit true acceptance and server acceptance time; atomic with encrypted requisites and command receipt.

`TermsDocumentInput` is either supplied full text/source locale or an existing actual document ID. `FieldDefinition` has `key`, locale→label map, optional locale→help map, optional exact permitted string values. Definitions must match `required_fields` exactly, with unique keys and no missing mandatory fields. At least a source-language label is supplied; no automatic translations or default legal-status choices. Existing limits remain 30 fields/key64/value2000/private-map20000 bytes. Use technical bounds of 1,000,000 UTF-8 bytes for document text, locale35, label/help2000, with nonblank text/labels and unique nonblank permitted values; these are input-size bounds, not contractual rules.

Enabled publication requires a valid actual document plus complete definitions. Disabled publication may omit both, or explicitly retain an existing real document with its field schema. It still records current admin/reason/version/effective/legal/terms/evidence provenance; emergency suspension is not blocked on invented text. A future publication stays future.

- [x] Write schema/publication RED: enabled missing/opaque document denied; actual supplied content/hash/fields persist atomically; disabled-without-companion succeeds; current nonadmin/stale-role/version/backdate rejected; mutation/TRUNCATE and populated downgrade refused; empty companion roundtrip works.
- [x] First PG RED command after root configures the isolated URL: `.venv/bin/python -m pytest -q --require-financial-postgres tests/postgres_financial/test_payout_contracts.py -k publication`.
- [x] Create the announced companion revision and metadata hook, plus actual SQL repository. Freeze its own DDL; do not import live mutated P01 tables into historical migrations.
- [x] Detect absent companion tables with a catalog read scoped to `current_schema()` before querying them; do not catch an UndefinedTable after aborting the transaction. Missing companion is explicit unavailable for enabled publication/new acceptance, while old history/status and observation paths remain functional. Disabled-without-document can still use the old publication fact.
- [x] Expand public requirements with `document`, `field_definitions`, `readable`, `unavailable_reason`; keep private legal/evidence/admin fields protected. Hash exact text without trimming or Unicode normalization; preserve HTML-like text as data. Rendering belongs to 9g-c.

## Task 3 — Explicit acceptance and retained-hash compatibility

**New publication fields:** `document=None`, `field_definitions=None`. **New requisites fields:** `accepted_document_id=None`, `accepted_document_hash=None`, `accepted=None` (strict bool when supplied). A new store requires accepted is true and exact current requirements/terms/document/hash after the existing User→requirements barrier; validate submitted keys and permitted values. New reserve requires the frozen acceptance bound to its own requisites/current readable publication under the existing money locks. No new User/wallet is discovered after item locks.

Do **not** put this new-acceptance gate inside `_current_requirements` for all historical admin/result paths: old prepared requests/history retain their original facts and real observations remain recordable. New store/new owner reserve must pass it; existing state/history/P1 safety checks still apply to all money as before.

**Hash rule:** project `asdict(command)` through an explicit whitelist of the new optional fields, removing them only when unused/None. Do not globally drop defaults, false, zero or old nullable observation fields. Preserve existing details HMAC/observation digest behavior. Money is already int by hashing time. Check a retained same-key command before dispatching the new document gate; matching old replay can return the old original receipt, but a fresh key cannot accept opaque terms. Never enrich or rewrite an original cached receipt to a newer document/state.

- [x] Write RED comparing hardcoded pre9g payload dictionaries/hashes to extended DTO defaults; include disabled publication, opaque old publication, encrypted requisites and unchanged integer request commands.
- [x] First RED command: `.venv/bin/python -m pytest -q tests/unit/test_payout_command_compatibility.py`.
- [x] Implement the payload projection and atomic document/acceptance operations. Partial/mismatched document proof, false/omitted acceptance or mismatched fields fail without encrypted snapshot/receipt insertion.
- [x] Real PG old-shaped retained publication/store receipt fixtures preserve original ciphertext/result/hash and replay with optional fields absent. A fresh key with the same opaque source fails. No production compatibility bypass or backfill is added.
- [x] Real paid fixture creates an integer Request receipt with the exact unchanged pre9g request payload shape/hash; signed equivalent string replay returns the same original request and no extra journal entry. Add changed payload conflict and changed-publication tests.

## Task 4 — Own safe operation recovery and masked requisites

**Operation status:** signed body is only auth envelope + `operation_key`; no actor/recipient/action selector. Lock actual actor User through the existing command barrier, authorize current owner status, then query the command under READ COMMITTED and take fresh server `observed_at` after the wait. No receipt, wallet, request or state is inserted.

Return `recorded=true`, safe original action/result, `recorded_at` and `observed_at` only for `StorePayoutRequisites`/`RequestPayout`. Requisites safe receipt: IDs/mask and any originally recorded public document metadata. Request safe receipt: request/requisites/requirements IDs, exact-string amount/RUB, original times, state/version/execution ID/block code; never fence, raw input, payload hash, encrypted fields, private reason/legal/evidence or arbitrary nested JSON. Unsupported administrative actions return a safe unavailable error with no action/result, **not** false absence. No own row after the barrier returns `recorded=false` with `observed_at`; this is an observation, not a durable key reservation or proof against a delayed original request.

**Masked list:** own rows only, deterministic recorded-time/ID order; return IDs, requirements/document version/hash when bound, time, mask, usable flag and safe unusable reasons. No plaintext name/account/legal status, ciphertext, fingerprint or key ID. `usable` checks gates, current readable requirements/acceptance and current key/authentication prerequisites; key loss/wrong-key gives false, never failure to read masks. Any internal authentication check discards plaintext and never exposes it. Usable refers to requisites prerequisites, not money eligibility/capabilities; no wallet upsert/readiness claim. Paging/context are deferred.

- [x] Write actual signed TG/MAX RED for lost-response recovery, actor-only lookup/list, forbidden selectors, unsupported admin receipts after demotion, poisoned extra cached fields, current blocked role, pause/key-loss readability, wrong-key usability and no plaintext/hash leakage.
- [x] First PG RED command: `.venv/bin/python -m pytest -q --require-financial-postgres tests/postgres_financial/test_payout_recovery.py`.
- [x] Implement the two service/repository reads and POST routes; responses are no-store and use Task 1 serialization. Lookup never requires retransmitting details or the encryption key.
- [x] Two real sessions: hold an executing owner's User barrier and insert receipt without committing; lookup must wait, then see committed receipt via fresh query. Rollback yields known absence. After known absence, a delayed same-key request may still record; lookup never creates a new key or mutation.
- [x] Forward an actual ASGI request through a response-dropping test transport after commit; observe network error, then recover by key with exactly one command/movement. No automatic retransmission or browser persistence implementation in this stage.

## Task 5 — Exact revision fixtures, regression and handoff

- [x] Update positive head fixtures to run the actual companion migration, publish visibly synthetic full text/field labels through the real admin command/API, and send exact explicit acceptance. Keep plaintext only in ephemeral test input; no legal text is invented for production.
- [x] Keep `test_empty_payout_revision_can_round_trip_without_descendant_teardown` exactly targeted at `financial_payout_v1`; no companion assumptions or removal of old safety guards.
- [x] Preserve the P1 populated test's genuine phase `campaign_foundation_v1`→`financial_payout_v1` and all old journal/NULL protocol/decimal amount assertions. Replace direct un-stamped upgrade with the isolated Alembic helper so the actual version advances. Before its **new positive** publication/store, apply the actual intervening `checkout_v1`→`campaign_digest_v1`→companion chain, then publish synthetic readable text/acceptance; its new money must still fail on P1 history authority. Do not skip parent migrations or add an old-schema acceptance switch.
- [x] Separate exact-old-P01 migration tests populate immutable old opaque publication/encrypted requisites/old-shaped command facts as visibly synthetic compatibility fixtures (no invented settlement or available balance). New runtime reads and retained replay work without rewriting them; new acceptance fails while the companion is absent/opaque. Upgrade the real chain, publish a **new** readable requirements version and accept it; assert old facts/ciphertext/hashes remain byte-for-byte unchanged. Unit old-shape hash tests cover optional-default identity independently of current constructors.
- [x] Run owned payout tests including P1/history/projection/evidence guards and new contract/recovery/migration modules, existing legacy PG guards and payout repository/callback unit regressions. Use fresh `COVERAGE_FILE`, `COVERAGE_CORE=sysmon`, `--cov=ugc_bot` with the owned include list extended to new modules, and explicit `--cov-fail-under=98`; do not weaken the floor.
- [x] Run owned Ruff/format/mypy; record exact RED→GREEN logs, test counts and boundary limitations. Root owns fresh independent review and the next shared gate; serialize migration-heavy runs and confirm all owner PG processes ended at handoff.
- [x] Freeze source/DDL, update the task9g-a report/checkplan and stop. No 9g-b/c, 6c, activation, live call or commit follows implicitly.

## Plan self-review / current state

All Stage9g-a clarification requirements map to Tasks 1–5; 9g-b/c requirements are explicit exclusions. Existing P1 readiness and state-proof tests remain in the final gate. The first RED commands, old-default hash rule, exact prior-revision fixture path and safe absence semantics are fixed above. During preparation only this Markdown file was written. After explicit root GO, Tasks1–5 were executed; the final owned gate passed255tests/99.20% with unchanged98floor and fresh sysmon coverage, legacy10PG+52unit/callback passed, Ruff/mypy14/30format clean. DDL is financial_payout_contracts_v1→campaign_digest_v1; root registered metadata. The exact prior-revision fixture, P1 populated boundary and privacy validation follow-up remain in the final gate. Outputs use the existing P01 dictionary/result style with an explicit validated owner-receipt whitelist. Source/DDL are now frozen and all owner PG sessions ended; root owns independent review/shared gate. Full evidence, exact interfaces and limits: /tmp/umc-full-sprint-reports/task-9ga-report.md.


## Final bounded privacy review fix

The255test/99.20% complete owned gate and legacy10PG checkpoint predate a fresh review finding in failure(ValueError). Exact safe-code normalization now replaces arbitrary service ValueError text with constant503 and also sanitizes caught safety/masked reason fields; no prefix/regex admission and no money/history/DDL change. Actual signed TG/MAX read/mutation RED produced9failures; latest pure payout suite120passed, public-code helper100% coverage/explicit98, Ruff/mypy15/31format clean. Root explicitly released PG to9f and approved pure verification for this follow-up. No new PG run was started; complete post-fix PG carry is root-owned when the slot becomes available. Source/DDL frozen pending independent recheck.


Final no-PG privacy carry: a lowercase poisoned retained block reason also failed RED, so recovery now admits only exact known server block codes (including empty) and rejects unknown code-shaped content safely without rewriting history. Latest final pure gate task-9ga-public-errors-coverage.log:123passed,100% coverage of payout_contracts+payout_errors, explicit98/sysmon; Ruff/mypy15/31format clean. The255/99.20complete PG checkpoint still predates these bounded privacy fixes; root owns post-fix PG carry. All owner PG sessions remain ended; no further source/DB work scheduled.
