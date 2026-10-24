# UMC Messenger Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Root's explicit ownership/no-subagent/no-commit controls take precedence. Implementation authorized by root after the shared gate on 2026-10-24; PostgreSQL work was separately released against financial_payout_contracts_v1; the scoped execution evidence is recorded below.

**Goal:** Authenticated MAX advertiser → actual native Telegram proposal → explicit original-MAX confirmation → attach an unused Telegram ID to the same canonical UUID for existing checkout.

**Architecture:** Dedicated attach-only service and caller-transaction repository. Persist safe challenge/claim/command facts; derive a live URL only in a currently authorized response. Intercept reserved Telegram starts before ordinary signup; never reuse the legacy Instagram account-moving helper.

**Tech Stack:** Existing FastAPI/aiogram, SQLAlchemy/PostgreSQL/Alembic, Pydantic SecretStr, standard-library secrets/HMAC/SHA256, existing Mini App shell and Playwright.

**Spec:** `docs/superpowers/briefs/umc-full-sprint/task-9f-messenger-linking.md`, especially its appended root decisions. The brief carries the full contract; this plan names execution boundaries and tests without duplicating it.

## Global Constraints

- Root gave source GO after the shared gate and separately released the PostgreSQL slot. Same shared worktree/branch; no commits, live calls, actual credentials, activation or deployment.
- Root accepted: attach-only; separate TG canonical User is conflict regardless of apparent emptiness; no merge/delete/detach; dedicated canonical unpadded base64url secret with ≥32 decoded bytes and a key ID;600-second TTL; MAX age≤3,600 seconds and future skew≤60 seconds;5 new issuances/current owner/rolling hour. Exact replay/current-active read is not a new issuance.
- Preserve current UUID, role/admin/status, created_at, profiles, country/language, referrals, money/history/order graph. No wallet/order/creator-profile/history locks or financial events. Issuance/proposal/confirmation hold the actual advertiser-profile KEY SHARE barrier after the original User lock and before identity/challenge locks. Both IDs already on the same User keep9e handoff unchanged.
- Never store clear token/launch URL in immutable results/facts/logs/browser storage. URL derivation requires current original signed MAX owner, active live challenge and matching available key/bot scope. Historical receipt and current state are distinct.
- While linking is disabled, safe historical/current-binding reads, exact receipt replay and reserved-prefix interception remain available. No new issuance/proposal/attachment occurs; no launch URL or confirm capability is exposed. Original-owner revoke can cancel an unconsumed challenge without detaching a completed pair. Disabled/missing capability never falls through to registration.
- Native proof is actual private sender and actual configured bot scope after the production secret check; no body boolean/header becomes proof. Production already rejects missing/wrong secret. Every malformed `lk1_` command terminates before normal registration/referral.
- **Root-approved native cap:**20 new reserved-link attempts per `(actual bot ID, actual native sender ID)` per rolling ten minutes, valid and invalid together; the twenty-first is refused. Exact immutable source replay is exempt. Counter has no User FK and creates no canonical User.
- The additive `messenger_linking_v1` revision follows actual coordinated stable `financial_payout_contracts_v1`, whose parent is `campaign_digest_v1`. Its builder and revision are frozen. No9ga API/service edits. Root owns central config/model/container/types/API/app/webhook integration; this worker owns new modules/tests and narrow linking UI/checkout/HTML/CSS.
- Real RED→GREEN, separate-connection PG races, native/HMAC/runtime and real-browser verification; keep98% without new no-cover/floor changes. Root owns independent review/full gate/integration commit.

## Review Focus

- Malformed reserved start or unknown native visitor falling through to automatic User creation — Task4.
- Unknown HTTP result or key rotation resurrecting a bearer URL/old current-pair claim — Tasks1,3,5.
- Ordinary signup winning the unique-ID race and being silently adopted/deleted — Task2.
- Legacy MAX remap, changed status/profile/admin or identity after proposal granting old-owner authority — Tasks2–4.
- Real host click capability,320px layout, malicious display names and input-bearing exception logs — Tasks1,4,5.

## Files and fixed interfaces

New files:

- `domain/messenger_linking.py`: `MaxLinkActor`, frozen `LinkScope/LinkContext`, safe `LinkReceipt`, nonpersistent `LinkView`, ephemeral `NativeLinkProposal` with safe repr.
- `application/messenger_linking_ports.py`; `application/services/messenger_linking_service.py`.
- `infrastructure/messenger/link_tokens.py`; `infrastructure/messenger/telegram/messenger_linking.py`.
- `infrastructure/db/messenger_linking_models.py`; `infrastructure/db/repositories/messenger_linking.py`; `infrastructure/memory_messenger_linking.py`.
- `container/messenger_linking_factory.py`; `miniapp/messenger_linking_api.py`; `bot/telegram/handlers/messenger_linking.py`.
- `miniapp/umc-messenger-linking.js`; CSS namespace `.umc-messenger-linking` only.

Paths above are relative to `src/ugc_bot/`. Coordinated migration: `infrastructure/db/migrations/versions/messenger_linking_v1.py`.

Repository contracts are defined by `application/messenger_linking_ports.py`: create/read/confirm/revoke/record_native/propose use explicit caller `session`, a fresh `clock` callback, and context/proof factories where needed. Security decisions take server time after the User/role/identity waits. Commands return safe `LinkReceipt`; read returns `LinkReadState`. Service owns transactions and returns a fresh authorized `LinkView`; private `propose_native` returns a historical safe receipt. Receipt serialization never accepts a live URL.

Token adapter: `derive(LinkContext)->str`, `verifier(token)->str` (SHA256 hex), `launch_url(context)->str`. LinkScope also freezes the domain-separated SHA256 fingerprint of current configured MAX bot scope; current MAX HMAC does not revive an old challenge after bot rotation. Canonical domain-separated HMAC-SHA256 over frozen context plus32-byte CSPRNG salt produces32 opaque bytes;43 base64url characters plus `lk1_` fit Telegram's64-character limit. Persist verifier/context/key ID only. Actual Telegram bot ID comes from configured Bot/installed `extract_bot_id`, not the request. Current-key/key-ID or bot-scope change makes an old challenge unavailable, without guessing an old key or using a new key for old context.

Proposed MAX routes: POST `/miniapp/api/messenger-links/telegram/{challenge,status,confirm,revoke}`. Strict signed MAX envelope; challenge adds operation key; status optional opaque challenge ID; confirm adds challenge/claim IDs and expected version; revoke adds challenge/version. No actor/TG ID/name/verified/admin-override body authority. Principal validates scoped freshness/HMAC and performs existing-only lookup; never `_ensure_user_and_get_id`, `_ensure_recent_user_and_get_id`, `_checkout_actor` or `set_user`.

Root owns these central edits; provide exact narrow patch requirements rather than editing them: `config.py` config/flat mapping/AppConfig; `models.py` one bottom registration import; `container/service_factory.py` and `types.py` one isolated service block; `miniapp/api.py` dedicated resolver/router; `app.py` router priority; `telegram_webhook_app.py` native interception. This worker owns both templates’ defer/empty mount, `umc-checkout.js` entry/refresh event and the new CSS block. Do not overwrite current partner/campaign/summary/9ga blocks. Use `repository_factory.py` only if root chooses that composition pattern, avoiding duplicate construction.

---

### Task1: Importable contracts, crypto and config privacy

**Files:** New domain/ports/token adapter; narrow `config.py`; `tests/unit/test_messenger_link_tokens.py`, `tests/application/services/test_messenger_linking_contracts.py`; existing config/startup-log tests.

**Interfaces:** Produces DTOs/crypto above and `MessengerLinkingConfig(enabled=False, token_secret:SecretStr, key_id:str)`. No generated secret fallback or reused provider/admin/payout key. Supply the config patch contract to root, who owns the central edit.

- [ ] First write the actual API/native RED entry tests named in Tasks3–4, against existing production apps; record their behavior failures. Collection/import errors are setup, not proof of an identity failure.
- [ ] Write pure contract tests for same-context replay, different owner/bot/salt/time/key,47-character payload and verifier, malformed/undersized key, default-off, unavailable rotation, safe receipt serialization and no token/key/URL in repr/startup/error logs.
- [ ] Run `.venv/bin/pytest -q tests/unit/test_messenger_link_tokens.py tests/application/services/test_messenger_linking_contracts.py --no-cov`; verify intended RED, then implement only minimal DTO/config/standard-library crypto and rerun green.
- [ ] Keep key material inside the adapter; persist only safe receipt/context/verifier. Handoff for review; no commit.

### Task2: SQL authority, immutable facts and narrow CAS

**Files:** New models/repository/memory fake; `tests/postgres_financial/test_messenger_linking_repository.py`, `test_messenger_linking_races.py`; later coordinated additive migration.

**Interfaces:** Implements caller-session repository methods above. Immutable challenge/claim/command/event facts plus small active-owner/TG-proposal projections and operational native counters. No raw-token/URL column/result or unregistered target-User FK.

- [ ] After GO, obtain actual stable9ga parent and table/constraint-name coordination before writing migration. Write PG RED for create→claim→explicit confirm, no new User,5/hour then refusal, replay/current-active exemptions,600-second expiry, changed payload conflict and fact UPDATE/DELETE/TRUNCATE denial including zero rows.
- [ ] Add rollback after attachment/before receipt: no partial attach/success. Existing separate target, both empty-looking and with real money/history, is refused without graph mutation. Assert unrelated canonical fields and financial/referral/history/order data unchanged.
- [ ] Add distinct-backend-PID races: two owners/one TG; two proposals/one challenge; concurrent creates; duplicate confirm; confirm/revoke; expired claim reuse; ordinary `set_user` signup/attach. Signup winning means conflict, never rollback-and-adopt/delete.
- [ ] Add pending challenge versus **actual legacy `link_max_account` remap**: after that helper changes MAX ownership, old challenge read/replay/confirm cannot attach or proclaim the old pair;9f makes no subsequent graph mutation. Snapshot after the legacy action to distinguish its behavior from9f. Do not call the legacy helper in9f production.
- [ ] Run `.venv/bin/pytest -q tests/postgres_financial/test_messenger_linking_repository.py tests/postgres_financial/test_messenger_linking_races.py --no-cov` for intended RED; implement minimal behavior; rerun green.
- [ ] Lock original User FOR UPDATE → actual advertiser-profile KEY SHARE barrier → identity coordination → challenge/projections; re-read scope/status/profile after locks. Attach only via narrow CAS of unused `telegram_id` on original UUID/current MAX ID, plus existing uniqueness. No full-model merge, foreign User lock, late User FK or wallet/creator-profile/history lock. Expired foreign reservation audit references its existing challenge. Use savepoint/whole-command rollback for unique race and only valid-transaction conflict facts.

### Task3: Existing-only MAX principal, service and signed API

**Files:** New service/API/factory and coordinated central blocks; `tests/application/services/test_messenger_linking_service.py`, `tests/postgres_financial/test_messenger_linking_api.py`.

**Interfaces:** MAX routes/service/receipt-view split defined above. Current role/profile/status checks apply even when admin; existing admin value stays unchanged, without override privilege.

- [ ] First ASGI RED: `test_signed_challenge_route_exists_without_auto_registration` expects controlled capability state for an existing signed MAX advertiser, rather than current404, and asserts zero `set_user`/country/referral calls. Add real HMAC/freshness/duplicates/extra-query/body/foreign-owner/current-remap cases.
- [ ] Write PG/factory RED for explicit displayed claim/version confirmation and exact lost-response replay; no attach before confirmation. Current ID/status/profile/admin/bot/key changes refuse stale authority and URL derivation; already-shared pair remains a no-issuance no-quota operation.
- [ ] Run `.venv/bin/pytest -q tests/application/services/test_messenger_linking_service.py tests/postgres_financial/test_messenger_linking_api.py --no-cov`; implement existing-only resolver, caller transactions and isolated factory/router in new modules, then provide exact imports/key/router/resolver patches for root; rerun green.
- [ ] Store `LinkReceipt` only; reconstruct live URL after a current original-owner/scope/active/TTL check. Consumed/revoked/expired receipt stays historical without old URL or false current-linked claim. Rebuilt factory recovers live URL without stored bearer. Native counter uses a separate short transaction before business locks.

### Task4: Production native proof and reserved interception

**Files:** New native adapter/handler; coordinated `app.py` and `telegram_webhook_app.py`; `tests/unit/test_messenger_linking_native.py`, `tests/postgres_financial/test_messenger_linking_native_runtime.py`.

**Interfaces:** Native private command is derived from configured Bot/token and real private non-bot Message/Update only after existing production secret validation. No public claim API/verified boolean. Reserved updates return before ordinary background dispatch; native fallback router precedes generic start.

- [ ] First real native RED: `test_reserved_malformed_start_does_not_create_telegram_user` sends authenticated production `/start lk1_!` with an unknown actual sender and synthetic external sends; assert no canonical User/referral/signup effect. This requires no pre-existing challenge schema and exposes current generic-start fallback.
- [ ] Add actual ASGI `raise_app_exceptions=False` cases: absent/wrong secret, wrong bot, groups/bots/missing sender, empty/long/bad/multiple args, unknown/expired/revoked token; every reserved case terminates without registration. Valid brand-new proposal still creates no target User.
- [ ] Add native source replay/conflict, first proposer cannot be replaced, source timestamps/minimal display snapshot, separate-target conflict and approved abuse-limit boundary/replay exemption with no User counter keys.
- [ ] Run `.venv/bin/pytest -q tests/unit/test_messenger_linking_native.py tests/postgres_financial/test_messenger_linking_native_runtime.py --no-cov` for intended RED, implement the new adapter/handler, provide root the exact app/webhook interception patches, then rerun green after root integration. Proposal persists before ACK; commit failure explicitly503. Reply failure after commit cannot erase proposal or claim linked. Ensure invalid Update/Pydantic and unexpected-error logs never print reserved text/token/URL; coordinate minimal input-safe logging if needed.
- [ ] Run existing webhook/start/referral/creator-IG/payment regressions. No external polling-offset claim.

### Task5: Real UMC UI, explicit consent and both-host compatibility

**Files:** New JS/controller; narrow mount/defer/CSS/checkout event; `tests/e2e/test_miniapp_messenger_linking_ui.py`; static-assets coverage.

**Interfaces:** Consumes current `LinkView`; confirmation contains displayed immutable claim/version only. Linked event triggers an existing signed checkout status read, never invoice/attach/payment commands.

- [ ] Write real-template RED for MAX entry → explicit Create → separate clicked Open; exact proposed TG ID/name/handle with account-access warning; explicit Confirm or revoke. Unknown create/confirm/revoke retains stable token-free command IDs/version/key across reload; no bearer URL in browser storage/history/datasets/console.
- [ ] Add stale/foreign/remapped/rotated/expired/conflict/old-success cases, malicious names, wrong claimant and hidden/back state. Only current server `linked` is success. TG host stays inert for interactive linking; normal checkout and same-canonical handoff remain usable.
- [ ] Run `.venv/bin/pytest -q tests/e2e/test_miniapp_messenger_linking_ui.py --no-cov` for actual missing-entry/controller RED. Implement isolated UI and event seam; live URL exists only in volatile authorized view, cleared hidden/expired/revoked/unmounted/identity failure. No automatic renew/confirm/open/pay.
- [ ] Verify ru/en/kk/be/uz,320px and390px, dark/light, native controls available/unavailable; MAX openLink only inside actual click. Bounded status polling stops hidden/terminal/expired; explicit Refresh remains. Run agreed carried checkout/selection/partner/summary/campaign/design tests; inspect local synthetic screenshots.

### Task6: Runtime proof, scoped floor and handoff

**Files:** `tests/postgres_financial/test_messenger_linking_checkout_runtime.py`; `/tmp/umc-full-sprint-reports/task-9f-report.md`.

**Interfaces:** Actual Container/MAX HMAC → production authenticated native ingress → SQL explicit attach → current TG principal and existing9e checkout; only external sends/invoice SDK and browser host boundaries synthetic.

- [ ] Write runtime RED: real MAX-only advertiser/order; unused native TG proposal creates no User; original MAX confirm retains UUID; explicit subsequent TG checkout/bot handoff resolves that UUID. Linking sends no invoice and changes no finance flags. Existing shared pair works; different canonical TG/money remains conflict.
- [ ] Prove rollback/current-role-admin-status changes, replay/rotation, legacy-remap denial and User→wallet concurrency with no late money/history lock. Do not claim the legacy creator helper is money-safe: its empty-orphan tests do not establish that. A separate full-goal compatibility audit of legacy linking against a financial MAX canonical remains required; broad legacy refactor is outside9f pending bounded review.
- [ ] Run all new focused PG/native/API/browser cases plus assigned carried9e/auth/start/IG suites. Ruff/format, mypy, node syntax and new-source98% coverage using `COVERAGE_CORE=sysmon`/task-specific data; no source-preload import artifacts, exclusions or threshold relaxation.
- [ ] Report actual RED/GREEN commands/totals, parent revision, lock/source/privacy/graph evidence, files and external config boundaries. Freeze for root's independent review/shared full `make fix` and integration; no commit, live activation, full-goal acceptance or polling guarantee.

## Self-review and blockers

The brief maps to Tasks1–6 respectively: crypto/config/privacy; SQL/CAS/conflict/races; current MAX API/replay; actual native proof/interception/limit; real consent UI/both hosts; actual checkout integration and scoped acceptance. Review Focus cases are explicit tests above. Central edits are named, and9ga API/service ownership is excluded.

Before code: root GO after its checkpoint, exact central patch coordination and actual stable9ga parent handoff. The20 attempts/10-minute native cap is now root-approved, as are the independent default-off flag and the advertiser-profile barrier. Already-approved root decisions are not reopened. No source/schema/test edit, DB call or gate was performed during this documentation assignment.

Execution update 2026-10-24: root GO after shared gate EXIT0 (5682 passed,1 skipped,98.25%;199 browser). Root central config/router/native pre-ACK hooks installed. No9f migration or PostgreSQL test until separate actual9ga head/slot release. Config and crypto require canonical unpadded base64url ≥32 decoded bytes; MAX scope fingerprint is mandatory, without a default.

Root-approved lock correction from actual PostgreSQL evidence: original owner User FOR UPDATE is acquired first, then advertiser-profile KEY SHARE, linking identity and challenge/projection locks. NO KEY UPDATE allowed an existing FK KEY SHARE holder to coexist until telegram_id unique-key UPDATE strengthened the User lock after role locks; the distinct-session regression observed that unsafe late upgrade. Stronger first-owner locking avoids this inversion. No foreign User, wallet, creator-profile or identity-history locks are added.

Final bounded review correction: immutable unexpired waiting/proposed history must agree with the active original-owner projection. A live proposed Telegram claim must also agree with the unique active Telegram projection. Missing/swapped projections fail closed before live views, issuance, new proposals, confirmation or revocation; no repair or foreign User lock is introduced. Expired/revoked/linked facts do not require obsolete pointers forever. Whitespace-only native ingress secrets disable new challenge material. Exact RED/GREEN logs and completed evidence live in `/tmp/umc-full-sprint-reports/task-9f-report.md`; planned checklist bullets above are the original acceptance plan, with actual completion limits stated in that report.
