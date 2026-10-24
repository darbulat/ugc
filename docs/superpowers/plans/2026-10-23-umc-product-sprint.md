# UMC Full Product Sprint Implementation Plan

> **For agentic workers:** Use the existing supplied design and specification. Execute tasks with explicit file ownership and independent review; keep the full goal active until all requirements are proven. Parallel work is limited to independent modules.

**Goal:** Implement all 20 tasks and all 30 acceptance criteria of the supplied UMC document.

**Architecture:** Extend the existing hexagonal Python backend and immutable ledger. Keep the existing Telegram/MAX HTML/JS clients and apply the provided design assets. Bind money commands to persisted authenticated facts, not client-supplied entitlement.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy/Alembic, PostgreSQL/PostGIS, aiogram, HTML/CSS/JS, pytest and Playwright.

**Spec:** `docs/superpowers/specs/2026-10-23-umc-product-sprint-design.md`; complete original `docs/product/UMC-developer-sprint-2026-10-22.html`.

## Global Constraints

- Money uses integer minor units and explicit currency. Preserve shared recipient-row writer barriers, immutable history, ownership and caller transactions.
- Selection=50000, accompaniment=120000, management reward=60000 RUB minor units. Referral basis excludes accompaniment.
- claim deadline=due_at+14 days; objection window=first claim+72 hours; hold=success_final+14 days. Never infer success from silence of both parties or failed objection delivery.
- Grades 0/100/200/400 unique verified creators -> 10/12/15/20%; client 10%; both sides 3% after their referred user's first anniversary. Snapshot at payment with overrides.
- No historic money backfill, fabricated legal approval, simulated bank success, guessed social metrics or exposure of another manager's network.
- Work in `feature/umc-product-sprint-full` in the attached worktree. Do not alter the user's dirty primary checkout. Run `make fix` before commits; retain coverage floor 98%.
- Canonical baseline is 6505af2. Original spec, design-system attachment and all acceptance criteria remain in scope throughout staged delivery.

## Review Focus

- Repeated/reordered payment, claim, delivery, refund and payout events must not duplicate money or erase failures.
- Concurrent workers and admin commands must serialize against the same wallet/item locks; test actual PostgreSQL sessions.
- A manager may also be a referrer, without merging economic grounds or seeing another recipient's data.
- Failed external notification, unknown bank response, due-date change and partial delivery must preserve truthful state.
- Old users/orders and Telegram/MAX registration, login, language/currency and payment flows must remain usable after migrations and UI changes.

## Execution and ownership

### Task 1: D01 / D02 canonical profiles and social accounts

**Files:** new `domain/social.py`, `application/social_ports.py`, `application/services/social_account_service.py`, SQL/memory adapters; extend profile ports/adapters and Instagram verification as needed. New migration `creator_social_v1` follows `management_reward_std`. New social/identity service and PostgreSQL tests.

**Interfaces:** one creator/user owns multiple social accounts. A verified Instagram is required to add other networks; those links remain unverified. Persist platform/url/handle, known metric/source/time and work format; unknown metrics stay NULL. Expose `SocialAccountService.list_accounts`, `save_account`, `remove_account`, `next_platform` through a typed port. These backend methods are integrated into API/UI in Task 9, so backend completion alone does not close D01/D02.

- [ ] Write and observe failing tests for ownership, required IG verification, valid platform URLs, ordered prompts, absence of invented metrics, stable identity uniqueness and old profiles.
- [ ] Implement DTOs, service, SQL/memory adapters and non-destructive migration with duplicate preflight.
- [ ] Verify service behavior and actual PostgreSQL constraints/races; review the scoped diff.
- [ ] Integrate registration/profile API and UI in Task 9 before closing D01/D02.

### Task 2: U01 existing Mini App design-system integration

**Files:** `miniapp/app.html`, `miniapp/max_app.html`, new `miniapp/design-system/`, `miniapp/umc-app.css`, `miniapp/umc-shell.js`; focused browser/UI tests. This task owns HTML/static files only while Task 1 owns profile backend files.

- [ ] Import the supplied CSS, fonts and brand assets; preserve original provenance and fix package-relative asset paths.
- [ ] Adapt actual existing screens without replacing working IDs/events/auth flows. Implement theme sync, viewport/safe area, form loading/error and existing empty states; mirror main actions using supported host capabilities with browser fallback.
- [ ] Verify Russian/English/Kazakh and currency formatting; do not force RUB copy onto non-RUB legacy flows. Record uncovered font glyphs and use a coherent fallback.
- [ ] Render screenshots and run browser regression checks. New financial/social screens remain coupled to their real APIs in Task 9; no fake balances, backend TODO buttons or premature U01 closure.

### Task 3: R04 collaboration lifecycle and R02 notifications

**Files:** `domain/collaboration.py`, new application lifecycle port/service, SQL state/event adapters and migration `financial_collaboration_v1` after `creator_social_v1`; existing interaction/feedback handlers and scheduler integration.

- [ ] Test exact due+14d, claim+72h and success+14d boundaries, explicit agreement, actor/assignment ownership, immutable claim origin, due-date versions, reasoned dispute and failed-notification behavior.
- [ ] Implement persisted commands for assignment/start/claim/agree/dispute/expire/finalize and scheduler transitions with idempotency/version checks.
- [ ] Replace per-creator feedback cascades with durable campaign summaries while preserving payment/new-order/critical notifications. Notify the opposite party once per claim; record transport acceptance separately from read/consent.
- [ ] Exercise 30 creators with no 90-message cascade, a 71h dispute, both parties silent and failed delivery using the real ingress/factory/worker path.

### Task 4: G01 trusted attribution, counts, policy overrides and snapshots

**Files:** referral policy/count adapters and service; new immutable override/snapshot provenance migration; quote/capture wiring.

- [ ] Pin threshold/anniversary cases, first binding and self-referral prevention, count unique verified Instagram identities, first-vs-later-year per side.
- [ ] Implement admin-authorized period/side/recipient overrides with reason, author and immutable audit. Validate standard/override rates against the approved policy.
- [ ] Produce snapshots from server-owned facts at payment, freeze them across subsequent changes and expiry, expose rate/progress in Task 9.

### Task 5: R01 / M03 real monetary consumers and assignments

**Files:** financial command service/adapters, snapshot/obligation producer, durable inbox/router/factory/worker wiring, paid-item assignment lifecycle.

- [ ] Replace the universal unready router with typed transactional consumers. Unknown event types remain explicit failures; retry/durable inbox deduplicate both transport and business grounds.
- [ ] Derive client/creator/management entitlement from persisted payment/delivery/assignment/success/policy facts. The manager fixed-fee primitive must not accept caller-invented funding or success.
- [ ] Issue client and author commissions independently (same recipient allowed), management separately. Run pending/hold/available transitions from the appropriate confirmed events.
- [ ] Verify retries, out-of-order delivery, concurrent workers, role changes and actual rollback with real PostgreSQL sessions and public ingress.

### Task 6: R05 corrections, replacements, refunds and debt

**Files:** financial adjustment/case services, immutable command/audit storage, admin API and UI in Task 9.

- [ ] Cover 30 paid/25 delivered/5 refunded -> base 1250000; partial component refunds; <=20% replacements and reviewed exceptions; no replacement after completed work.
- [ ] Write linked compensations without editing source entries; cancel old pending author ground before replacement. Handle pending/available/reserved/paid cases distinctly.
- [ ] Block affected reserved payouts; paid corrections create debt/case, repayment writes recovery. Only accepted contractual terms authorize manager future offsets.
- [ ] Add reason/proof/current-admin/versioned review and reconciliation alerts; verify the complete immutable journal and projections.

### Task 7: P01 reserve/manual payout and F01 bank integration

**Files:** payout request/allocation/execution storage, service, bank port/adapter, protected admin/partner endpoints and worker.

- [ ] Atomically reserve only available, validate access and idempotency, freeze allocations and capture required lawful recipient details securely.
- [ ] Implement reviewed manual paid/rejected transitions with unique bank reference, reconciliation and 72h queue/SLA. Never use a generic CRUD mark as a bank fact.
- [ ] Implement the selected provider's authenticated idempotent transfer/status/reconciliation adapter after provider/access is supplied. Unknown timeouts cannot retry money blindly or release reserves.
- [ ] Verify concurrent requests, repeated callbacks, disputed reserve and post-paid refund. Real bank credentials/approval remain external evidence, not synthetic test data.

### Task 8: S01 accompaniment order and reliable manager lead

**Files:** quote/order services, persistent lead and outbox, payment invoice API/handler.

- [ ] Add server-validated self-service/with-manager selection and 170000-per-author total, shared with bot/Mini App. Persist order+lead before admin notification and deduplicate clicks.
- [ ] Preserve existing multi-manager assignment and direct client-to-author honoraria. Connect accepted payment/assignment to management entitlement.

### Task 9: R03 / M01 / O01 and integrated client screens

**Files:** new focused Mini App routers/view services, root api/container wiring, bot menus and locale texts, HTML/JS owned after Task 2 integration.

- [ ] Expose authenticated own referral link, both rates/override/progress, own network and entry-level financial history with pending/hold/available/reserved/paid and missing confirmation reasons.
- [ ] Add a visible partner-program entry for every role, including manager. Show management and referral earnings independently; no foreign data through IDs/query filters.
- [ ] Complete multi-step brief/filter/package/payment/status path inside Mini App using a real Telegram invoice URL, retain bot fallback and record funnel steps/dropoff.
- [ ] Integrate socials, sequential prompts and platform filters; real financial claim/dispute/refund/admin/payout screens and loading/error/empty/blocked states using UMC components.
- [ ] Run actual browser/E2E journeys for all roles, mobile sizes, themes and keyboards; recheck existing flows.

### Task 10: M02 own-network moderated campaigns

**Files:** campaign/consent/segment/quota models, commands, moderator API, delivery outbox/worker and manager screens.

- [ ] Restrict audience to owned, registered, opted-in creators with a usable channel; deduplicate recipients, enforce quotas and unsubscribe/consent.
- [ ] Persist submitted/reviewed campaign and delivery/response events; moderation precedes dispatch. No arbitrary contacts or base export.
- [ ] Verify moderation/ownership/limits/retries and truthful delivery/response reports end to end.

### Task 11: P02 subscriptions after paid pilot gate

**Files:** subscription policy/entitlements/usage service, tariff/payment and campaign integration, admin pilot evidence.

- [ ] Persist actual pilot payment/reuse evidence; automation cannot activate before three distinct paid manager pilots.
- [ ] Implement configured tariff scope and quotas, paid entitlement activation/expiry and renewal without leaking the shared base.
- [ ] Verify unpaid/expired/repeated payments and concurrent usage; close only after actual paid/reuse evidence.

### Task 12: A01 trustworthy campaign analytics

**Files:** campaign event/attribution source adapters, analytics service, report/export and own-campaign UI.

- [ ] Establish agreed sources for actual views/clicks/leads/sales and paid 2–3 campaign pilot evidence; never synthesize missing counts from Instagram profile averages.
- [ ] Implement scoped idempotent event ingestion, attribution rules, CPV/CPA/CPL with zero-denominator handling and source/time/provenance.
- [ ] Verify duplicates, attribution boundaries and permissions; report actual metrics and unknowns transparently.

### Task 13: L01 approval-controlled lawful payout/expiry

**Files:** recipient legal status and approved terms process, gross/actual lawful adjustments/net view, expiry warning/dry-run/audited batch only after external approval.

- [ ] Retain explicit off defaults for any automatic 365-day expiry or invented 6% deduction.
- [ ] Persist real approval identity/reference/date and accepted applicable terms; never accept fabricated approval from a public request.
- [ ] Implement approved withholding/expiry rules only after user supplies accountant/legal decisions, with warnings, dry-run, immutable operations and refusal without approval.

### Task 14: T01 full acceptance, observability and release evidence

- [ ] Complete AC01–AC30 using runtime tests at their actual scope, including a 30-author order, client+creator+manager same-recipient case and reverse refund/payment order.
- [ ] Run `make fix`, unchanged 98% coverage floor, real isolated PostgreSQL migration/concurrency checks, E2E and mobile visual review. Report failures by name.
- [ ] Perform independent security/spec review of the final branch and fix findings; review runtime DB privileges, feature flags, policy/refund/terms inputs and rollback.
- [ ] Produce a final per-requirement evidence audit. Keep the goal active while any code, external condition, required test or actual launch criterion is unproven.

## Progress ledger

### Paid selection interest/read checkpoint (still not final acceptance)

Task6a now routes the real financial offer-confirm flow to immutable interest,
versioned initial assignment and a durable contact-delivery job. Unique
creator/verified Instagram and purchased-pool checks preserve waitlist and
prevent duplicate positions; actual accompaniment controls manager assignment.
Telegram/MAX bypass the untracked old sender for this flow. Own-client signed
selection read separates current assignment from prior accepted deliveries and
uses one read-only repeatable snapshot. Fresh focused gate after review fixes:35passed,99.57% of
233 statements in six modules;98% threshold unchanged. Native/legacy targeted
regression122passed. See `briefs/umc-full-sprint/task-6a-report.md`.

Task6b implements provider acceptance separately. Actual closure/refund window,
refund/replacement/correction producers and client maturity remain open; no
30/25/5 acceptance or whole-branch completion is claimed here.

- Baseline: 6505af2; clean managed worktree with isolated dependencies created. Full non-E2E baseline started before implementation.
- Previous audits are context, not evidence that unfinished requirements are complete. No backlog task is closed by this plan itself.

### Integration checkpoint (work in progress)

- Task 1 supplemental social storage/service and stable Instagram uniqueness: focused backend report `/tmp/umc-full-sprint-reports/task-1-report.md`. Root added signed Telegram/MAX social API, current status/ownership checks, strict payloads, production repository/verifier wiring, and a real PostgreSQL save/rebuild/read/remove journey.
- Task 2 existing-screen UMC integration and Task 9 social editor: 30 combined Chromium checks and 2 real ASGI static checks reported; existing 179 IDs preserved in both templates. Reports `/tmp/umc-full-sprint-reports/task-2-report.md` and `task-9-social-ui-report.md`. Actual-device/localization and remaining financial screens are still open.
- Task 3 lifecycle: persisted item-scoped state/events/notices/maturity schedule; signed public commands/status wired to the real container. A fresh SQL transaction now begins before its first strict repository operation. The combined scheduler starts the versioned deadline sweep only with financial core enabled. Unit and real PostgreSQL integration prove silence expiry, accepted-notice finalization and separate14d maturity. Durable external notice delivery is in progress; no money producer is claimed complete.
- Task 4 history and Task 5 ledger prerequisites are in progress with their own scoped test evidence. Historical verification reader is wired; pre-cutover/missing coverage fails unavailable. No inferred past verification dates.
- Root financial delivery router now awaits explicitly registered handlers in the caller transaction. Kafka-disabled workers run financial deliveries without claiming legacy activation events. Notification requests have a separate owner and are excluded from general financial claim/recovery. Real PostgreSQL verifies handler write and publish marker commit/rollback together. Monetary handlers remain unregistered until trusted producers are ready.
- Full shared-tree run reported4554 passed,19 skipped,34 deselected,98.15% coverage but8 old downgrade-test failures/setup errors from testing old migrations against new descendants. These8 now pass with actual revision-specific isolated fixtures; production immutable downgrade guards remain intact. This is not a stable final `make fix` gate.
- All20 backlog tasks and30 acceptance criteria remain in scope. No deployment, real messages, bank transfers, fabricated legal approvals or invented paid pilot evidence. External provider/approval/pilot question remains pending.


### Client entitlement and work UI checkpoint (still not final acceptance)

- Client producer now runs from confirmed Telegram capture through the actual `build_outbox_deps` financial worker. It reloads provider intent/payment/items/allocations/approved policy, validates immutable payment-time attribution, excludes accompaniment, freezes rates and writes journal plus immutable assessment plus publish marker in one transaction. Scope locks remain User/wallet → order/payment → explicit shared history barrier → sorted items. Missing history remains unresolved.
- Real PostgreSQL proves first-year10%/later3%, unchanged recipient after correction, no-referrer potential, authority forgery rejection, duplicate/concurrent processing and rollback. Replay after later refund returns the original immutable receipt; changed stored source is a payload conflict.
- Capture now locks payer before outer order coordination and freezes authoritative history before item writes. Delayed callback preserves original partner/registration; unknown pre-cutover history records the real paid fact without inventing a commission. Exact paid-receipt replay does not require new history.
- Protected recent signed Telegram/MAX admin override API supports create/revoke/supersede/list/read with actual current admin checks, strict fields, reasons and versions. A real PostgreSQL API → capture → worker test uses the approved20% override and proves later admin demotion does not rewrite its snapshot.
- Work status/command API now returns server-assessed actor_id, allowed_actions and is_current under the same item transaction. Actual state/time/current roles decide controls; historical or stale result versions expose no actions. Both Mini Apps now have the real collaboration screen. Task9a report documents65 combined browser tests and explicit signed-provider/device boundaries.
- General router now registers creator/management work consumers under the existing core flag, using the same WorkFinancialGuard as the client handler. First actual capture → assignment → claim → opposite agreement → author/manager hold proof is green; full Task5d review and edge checks remain in progress. Financial inbox types still exclude separately-owned notices and capture intents.
- A real SQL delayed-client/dispute test proves a case persisted before the payment consumer puts the related new client ground directly into blocked (other item remains pending), linked to the actual case/event, without waiting for the work outbox event. Reserved/paid cases still require the later dedicated payout/correction coordinator.
- One root verification selection passed55 tests with99.17% coverage of client producer/funding validator/admin API before the later dispute helper addition. The dispute extension separately passed8 unit and1 actual PostgreSQL test. This is not whole-project coverage or a final make-fix result.
- Independent read-only audit covers all20 tasks and all30 AC at `/tmp/report/umc-acceptance-audit-2026-10-23.md`; updated Canvas explicitly distinguishes the worktree from main. Its conservative task/AC statuses do not close unfinished business paths. The one full-run owner-error regression is corrected and its related12-test selection passed; a new full gate is still due.
- Ongoing independent work: native notice launch buttons and generic receipt envelope; atomic self-service/accompaniment intake and durable lead notification; author/management maturity and disputes. Next root stage is actual confirmed selection delivery and client maturity, followed by authoritative refunds/replacements/reserve/manual payout. No flag activation, deployment, real sends, bank action or invented external approval/pilot evidence.

### Shared gate checkpoint after Task6b/9d

Full `make fix`: format/Ruff/Mypy passed;5268tests passed,3failed,1skipped;
global coverage98.27% with unchanged98% floor and actual PostgreSQL enabled.
The three empty financial-worker-result failures are under investigation; this
is not a passed gate. Fresh independent Task5d/6b review:60passed, no findings,
ready for those slices only. A real same-person manager/client-referrer/creator-
referrer runtime and signed own-partner view passed along with14 work regressions.
M02 policy/grant/explicit-consent foundation is now being implemented from
`briefs/umc-full-sprint/task-10-campaigns.md`; no send activation or quota
values have been invented.

### Passed shared checkpoint before M02 and checkout

Full `make fix` now passes:5280passed,1skipped,98.27% global coverage;
format/Ruff/Mypy pass. Actual PostgreSQL is required; live E2E is excluded.
Prior empty-result failures were reproduced with100 older pending financial
events. Test-only target-event draining now waits within a finite budget and
fails on target retry/error/no-progress; production batch and money rules are
unchanged. Exact previously failing prefix:99passed. Joint Mini App browser
regression:125passed. Log `/tmp/umc-full-make-fix-rerun.log`.

Actual99→100 current grade transition before any work success is verified by
the production partner view; a prior capture keeps99/10% even though current
grade is12%. Both client10% and separate work hold are preserved. This and the
same-person three-ground test improve AC05/08/21 evidence, but do not close
refund, payout, checkout or whole-product acceptance. M02foundation and checkout
preconditions are the next implementation wave; this gate predates those edits.

### Task10a/3c recheck and Task3d weekly checkpoint

Campaign consent is bound to the exact inviter/binding observation the creator
reviewed; stale A→B/A→B→A and pending-request retries are rejected. Inactive
publisher grants remain revocable. Summary source preflight covers all five
required relations. Independent repeat review:95backend/48browser, all three
findings resolved, narrow slices scope-ready subject to integration. Task10a
focused75checks/41PG/99.75%; summary20PG/99.21%; jointbrowser173passes.

Weekly CampaignDigestService and actual production scheduler cutover now pass
60checks/99.63%271behavioralstatements with explicit unchanged98floor.20actualPG
cases include30creators/actualfactory, currentfinancialmanager scope, unchanged
24h/72h cadence,7dayminimum, rollback/concurrency/crash/late-receipt and provider
reference-reuse protection. campaign_digest_v1 follows frozencheckout_v1.
CAMPAIGN_DIGEST_ENABLED defaultsfalse and was not activated; old per-author loop
is removed from both production entrypoints, critical workers stay independent.
Independent Task3d review is running; P01/checkout still in progress. The prior
5280pass sharedmakefix predates all these edits and is not a current-wave gate.

### Review follow-ups before the next shared gate

Task3d review resolved its accepted-but-unapplied reference-reuse finding.
Complete post-fix focused verification:61passed/99.63%, explicit98floor; independent
affected3PGcases and reversed original probe passed. Scope-ready only, no fullgate.

Checkout9e checkpoint289backend/73browser/98.36% was followed by fresh independent
review with three reproduced gaps: new native authorization while stop flags
are off, immutable original checkout owner after order reassignment, and browser
known failed/unknown link result replay trap. Original implementer is fixing
those findings; checkout remains unaccepted pending repeat review.

P01 checkpoint103passed/98.96% was followed by approved immutable request-state
authority hardening; current focused run is in progress.9g UI audit identified
exact-string money, readable immutable terms, safe operation recovery and server
capabilities as concrete prerequisites. Root accepted staged design only, no9g
implementation yet.6c correction/refund/replacement design has a separate read-only
review in progress; no refund anchor or partial manager reward rule was invented.


### Checkout9e resolved; P01 historical-authority stop pending

Checkout original implementer reproduced/fixed all three review findings. Current
owned gate299backend/PG+78browser/98.38%; independent recheck302backend/PG+28browser
passed with all three findings resolved. This accepts only9e subject to integration,
not general MAX→Telegram linking9f or external activation.

P01 projection/event authority follow-up passed111focused/98.99%. Independent
review then reproduced a P1: balanced preserved foundation-era v1 journal reserve/
paid without P01 allocation/bank authority permits new reserve/review/start. A
bounded readiness fix is assigned; old history must remain readable and actual
bank observations retained unapplied. True legacy-only history is distinct.

The6c correction design now incorporates independent findings: shared cross-
producer proof ownership, gross/live funding split and early-observation identity,
cumulative component/obligation deltas, allocation-aware reserved/paid resolution,
and replacement commit/work-resolution/acceptance contracts. First6c-a1 positive
path is captured unassigned undelivered selection refunds after agreed due with
pending client compensation. No refund-window anchor was chosen; no6c source
implementation or broad acceptance is claimed. Latest fullmakefix remains the
older5280pass checkpoint pending stable sources and new shared verification.


Joint reviewed Mini App browser checkpoint:199passed in73.16s across actual
production design/social/work/partner/selection/summary/campaign-foundation/checkout
assets with synthetic signed API/native host boundaries. Log:
`/tmp/umc-joint-browser-reviewed.log`. No live provider, device QA or whole-money
claim.9f attach-only linking design accepted with safe parallel-signup conflict,
dedicated key, explicit original-MAX confirmation and no clear token in receipts;
implementation remains queued after current sharedgate.


### P01 recheck and current shared-gate fixture repair

Sole P01 history-authority P1 resolved; independent9casegroups prove both old
reserve/paid variants stop new money, observations retained unapplied, history
readable, true legacy-only rows allowed and new accepted P01 history usable.
Current owned123passed/99.00%, legacy10PG+39unit, quality clean.

First new sharedmakefix found11legacy SQLite fixture setup errors: PG-specific
campaign_digest EXTRACT DDL entered metadata.create_all. A standalone actual
integration repro failed identically. Payout interval DDL is also PG-only. After
SIGINT and completed cleanup (3370passed/1skip/11errors, interrupted; NOT a gate),
added tests/helpers/sqlite_schema.py used by legacy integration/admin/localE2E
fixtures. It excludes the existing unsupported tables plus payout/digest families;
production DDL and mandatory actualPG tests remain unchanged.13legacy integration
tests pass; shared selected SQLite schema creates76tables.

Fresh fullmakefix now running with new sysmon coverage, explicit unchanged98floor
and mandatory isolatedPG: /tmp/umc-full-make-fix-sqlite-repaired.log. The interrupted
run log is /tmp/umc-full-make-fix-reviewed-wave.log; standalone RED is
/tmp/umc-integration-sqlite-red.log. No broad success claim pending final exit.


### Passed shared checkpoint after P01/checkout/summary/digest review

Fresh fullmakefix EXIT0:5682passed,1skipped,105warnings in503.52s; global98.25%
(31945statements/559miss), explicit98floor; format/Ruff/mypy441sources clean.
Log /tmp/umc-full-make-fix-sqlite-repaired.log; fresh sysmon coverage
/tmp/umc-full-sqlite-repaired.coverage. Joint actual-assets browser gate199passed
in73.16s; inspected ru-light/kk-dark320checkout images, separate10capturetests
are duplicate visual evidence and NOT added to199. Source/test SHA256 checkpoint
manifest: /tmp/umc-reviewed-wave-source-manifest.json.

R02 amended scope andAC29 now locally confirmed at this checkpoint: actual30author
aggregate, retired both scheduler cascades, distinct critical notices/claim proof,
no silence/failure-as-success, scopedreview and sharedgate. This is local proof,
not live sends/activation/deviceQA. Canvas counts2local/15partial/3unimplemented
tasks,14local/13partial/3notpassedAC. P01 remains partial pending9gUI/corrections;
backendscope123/99.00+independent9groups ready.

Root accepted9f plan operational20native attempts/rolling10min, exactsource replay
exempt; originalMAX explicit confirmation and no separatecanonical merge remain.
9ga newcompanion contracts migration owns nexthead aftercampaign_digest_v1;9f
child follows actual coordinatedhead.10b design twoP1s resolved by independent
recheck; boundeddesignready only.6ca1 designready, no code yet.


### Current9ga/9f/9gb/10b source checkpoints

9ga actual owned gate255passed/99.20% sysmon with unchanged98floor and legacy
10PG+52unit passed. Subsequent privacy review reproduced arbitrary ValueError
text in read/mutation errors and unknown lowercase cached block codes. Fixed
with exact public-code allowlists in API, safety/masked reasons and recovery,
without rewriting old receipts. Independent post-fix123pure plus178 additional
route/recovery cases pass; root separate108pure pass. The255PG checkpoint
predates those source-only fixes; independent3file PG carry remains queued.
DDL/source frozen; no9ga DB process remains.

Root released exclusivePG to9f only after9ga sessions ended and verified actual
sole parent financial_payout_contracts_v1. New actual messenger_linking_v1 child
exists and central models are registered. Root added default-off dedicated
validated config, strict existing-onlyMAX router, durable native preACK hook,
reserved outer middleware before locale/user metadata, fallback router and
factory/type wiring. Root154config/API/webhook and2actualdispatcher priority
checks passed; later158locale/dispatcher/checkout/webhook carry passed. Central
6source mypy clean. SQLite legacy helper excludes new PG-only link family and
5actual legacy integration cases pass; production DDL is unchanged.

9f SQL25 checkpoint passed, including actual distinct-PID key-share lock
inversion precursor RED: original-owner FOR UPDATE now occurs before role/
identity locks, so a concurrent role delete commits and confirmation rechecks
unavailable without attachment. This proves removal of the ordering hazard,
not a reproduced deadlock. Factory missing-native-ingress-secret RED fixed.
Actual Container/signedMAX/native/Telegram-checkout4runtime passed. Later8PG
authority probes reproduced borrowed foreign claim and resurrected revoked
projection; immutable transition/projection checks are being implemented.
No9f completion, source freeze or whole-tree gate is claimed.

10b1 source-only checkpoint125pure plus one additional unique immutable-envelope
case, scoped9source mypy/Ruff clean; no new SQL draft model/repository/migration
exists. Its prepared PG cases are unrun. Worker ended turn until explicit
release after9f and queued9ga independent carry. Existing shared consent SQL
changes also await that PG verification. Full M02 moderation/send remains open.

9gb read plan now includes independent six-point design revisions: typed
existing-only principal with native mapping checked inside RR; exact amount/
requisites preview; authoritative SQL queue membership including broken rows;
separate observation/action matrix; bounded masked/requirements collections;
raw source/column presence and proof matrix. Final escalation clarification
requires proven nonterminal state. New modules may proceed source-only without
editing frozen9ga writers or taking PG; root central hooks remain coordinated.
6ca1 has a separate plan-only worker, no source/SQL work or invented refund anchor.

### Current bounded reviews and next source wave

9ga independent frozen-source PostgreSQL/privacy gate passed48cases. The privacy
fixes are accepted within9ga; earlier255/99.20% is its owned checkpoint, not a new
whole-tree gate.9f also completed:209backend/98.53% plus44browser; both independent
findings were fixed. Fresh independent72PG+43service/factory passed, with all DB
sessions disposed before the next owner. Separate legacy IG/MAX compatibility
is outside9f's attach-only acceptance.

10b1 now owns exclusive PostgreSQL. Its actual campaign_drafts_v1 migration is
the child of messenger_linking_v1; root registered the review models/repository,
shared foundation repository, review/audience services and signed routes. Initial
51PG cases and route privacy RED-to-GREEN passed; the owned98floor gate remains
in progress. No moderation/send/response/report completion is claimed.

9gb source-only182pure checkpoint underwent independent review. Two source
capability gaps (ordinary-command physical dependencies and the frozen writer's
full-User observation dependencies) plus UTC-overflow cursor classification are
being fixed by a new bounded source owner. PostgreSQL and the owned98floor gate
remain unrun until10b explicitly releases the slot. The shared makefix5682/1skip/
98.25% predates all these source changes.

9h original read-only audit identified current native-mapping checks missing
from older payout/override ingress and a separate-account compatibility problem
in legacy creator linking. Root wrote a defensive typed-principal/conflict plan
at2026-10-24-umc-native-identity-fences.md; plan review is in progress. No9h source
fix or acceptance is claimed. Two prior delegated planning attempts were rejected
by automatic content review; they produced no implementation or additional probe.
The user was informed. The present work is ordinary defensive correctness only.

### Native principal source review and owner-screen plan

9h1source now frozen: existing-only signed financial resolver and explicit native
proof reach all14payout/3override HTTP paths. Current requester UUID/native mapping
is checked after the established complete sorted User barrier before authority,
replay, private response or mutation. No economic DTO/hash/receipt, recipient
funding check or lock strength changed.273pure pass; the new49statement principal/
resolver boundary has100%sysmon at98floor. Independent60pure/source review clear;
root separately53principal cases and centralAPI Ruff/format/mypy pass. Actual
two-sessionSQL and the shared gate remain pending, so9h is not closed.

10b1final198tests/99.76% includes actualPG and migration; independent70pure/source
review clear, independentSQL queued.9gb expanded actualsource/queue/keyset matrix
has passed bounded batches; a carried gate imported9h's shared HTTP wrapper while
it was changing and failed16cases. That mixed-source gate is not accepted. All
sources are now frozen for the new stable owned gate, preserving98floor.

9hTask2attach-only/typed conflict/external-proof availability plan has independent
design acceptance, no source yet. New9gc1ownerUI plan includes exact-string money,
current capabilities, opaque bridge request context, captured-operation recovery,
partner entry during stalled reads, allfive locales and strict owner-only scope.
Its independent plan recheck is pending; UI implementation remains unreleased.
6ca1implementation-plan review is also in progress, without source/PG work.

9gc1plan recheck has now resolved all three findings; root released only its
assets, narrow both-template bridge hooks/partner-busy exception and new browser/
static tests. Python backend remains frozen except the9gb owner's narrow reads.
First frozen9gb checkpoint510passed/99.48% across21modules; the subsequent approved
physical-only hint extension for store/publish/escalate still needs its own fresh
gate. It preserves semantic independence and readable money history.

6ca1plan review requested one blocking clarification: a late economic-scope change
must not discard an already actual trusted transport/bank result. Root amended
forward-retry versus unapplied-retention rules, delivery-service ownership/exact
two-session races, internal same-transaction gross assessment before receipt-last
success, and reuse of9h1 native proof at the complete sorted User barrier. Recheck
is pending; no6ca1 source/schema/PG release has occurred.

6ca1implementation-plan recheck now closes that finding and both clarifications.
Root released ONLY Task1new pure contracts/math files and their new tests; no
existing runtime source, factory, API, model, repository, migration or PostgreSQL
operation is authorized for that owner. Positive correction commands remain
unreachable. The full implementation and actual migration parent stay unreleased.
9gb physical extension observed9pure+9PG RED, then91readerpure and18actualPG
physical/independence cases GREEN; the reader PG suite now has65cases. Its new
fresh21module98floor gate is running. The earlier510/99.48 checkpoint predates
that extension and is retained separately.

Final9gb post-extension frozen gate581passed/245.38s/99.48% (1934statements/10miss),
explicit98floor; six readers793/796=99.62%. Ruff/format11files and mypy6 clean.
All builder processes ended, fresh0otherclient sessions/0private schemas and
verification engine disposed; root released exclusivePG to the original9gb
reviewer for independent closure. No whole-tree gate or P01 UI acceptance follows
from this scoped result.9gc1owner initial46browser plus45helper/static passed in
separate overlapping batches; late-preview cleanup and320MAX formatting remain
under active owner follow-up, independent UI review is pending.

9gbindependent closure accepted:167passed/79.82s =91ownedreaderpure+11sharedprivacy+
65actualPG. All three original findings and physical-source follow-up resolved;
fresh0sessions/0private schemas/0ownprocesses, engine disposed. Root released
exclusivePG to10b1's original independent reviewer next;9h1two-process SQL follows.
6ca1Task1contracts source checkpoint88pure/100%497statements, scoped quality clean;
fresh read-only contract review now in progress, no correction runtime/SQL exists.

10b1independent SQL closure56passed/27.48s, prior70pure/source clear; all sessions/
schemas/processes zero and engine disposed. Root released exclusivePG to9h1's
original implementer for real two-process mapping/barrier tests.6ca1Task1pure
contracts independently passed88cases, no bounded finding; runtime still absent.

9gc1owner source checkpoint146newcases(101browser+45helper/staticASGI) plus disjoint
217oldbrowser carry passes.28synthetic screenshots; root inspected RU320lightterms,
KK320darkunknown and KK320darkreview: maximum money stays one line, long IDs/text
wrap, secret fields blank, unknown intent explicit. Independent UI review then
confirmed two open lifecycle defects: delayed own/masked/detail renders erase an
active private form/acceptance, and late detail A replaces the latest selected B.
Original owner holds source freeze until collected findings are returned.9gc1
is not independently accepted;9gc2admin is plan-only work in parallel.

9gc1's two lifecycle findings now have permanent RED→GREEN coverage:16newcases
produced14fail/2pass on the original reviewed controller, then16passed after the
payout-local fixes. Fresh complete owned gate162passed/55.93s (117browser plus
45helper/static/ASGI); controller503be731, shared bridge/global/partner behavior
unchanged. Original independent reviewer is rechecking this frozen fix; acceptance
is still pending.9gc2admin implementation plan is written and independently under
review; no admin source has been released.

9h1actual SQL checkpoint677passed/275.02s with99.15%sysmon coverage over nine
unchanged runtime files at98floor. Only the new PG file then gained three tests
and stronger assertions; its final60cases passed36.40s, including54two-session
cases with distinct backend PIDs. This is not a combined680test claim. Builder
released PG with fresh0clients/schemas/processes and disposed engines. Original
independent reviewer now owns PG exclusively for the final60case recheck. Task2
legacy attach-only source remains unreleased; no current full-tree gate is implied.

Fresh independent closure now accepts both bounded checkpoints:9gc1reran all162
owner/helper/static cases in54.03s, re-read the local fix and inspected3regenerated
synthetic screenshots; both original findings closed.9h1independently reran60PG
in38.09s, all54distinct-PID races completed, freeze hashes unchanged. Fresh PG
release confirms0clients/schemas/processes and disposed engine. No independent
coverage or broad677repeat is claimed. Root released9hTask2source/pure only
(PG remains separately gated), and9gc2admin assets/narrow owner-template hooks
after its independent plan review returned ready. Whole-project, actual device,
bank/legal and full-sprint acceptance remain open.

Fresh U01 archive check confirmed the same ZIP SHA and all24packaged files
byte-identical (187653uncompressed bytes). The example already uses actual flat
asset paths; only the supplied README mentions obsolete Logos/Patterns paths.
Root corrected provenance's earlier claim that the example was edited. Manifest:
`/tmp/umc-full-sprint-reports/task-u01-archive-byte-audit.json`; recheck report:
`/tmp/umc-full-sprint-reports/task-u01-archive-recheck.md`. No runtime/asset changed;
U01 remains partial pending remaining screens and actual device QA.

Root's9h3remaining-caller source inventory and firstintake/collaboration plan are
saved; the latter is plan-only, not independently reviewed or source-released.
Collaboration's UserFKs require complete actor/party preparation before item,
and public status/command capability composition must not restart User locking.
Other snapshot/campaign/social callers remain explicit follow-ups.

Root now released6ca1Task2ONLY additive storage/source loading and exclusive
private schema/PG. Fresh staticgraph has sole headcampaign_drafts_v1; assigned
newfinancial_corrections_a1 parentcampaign_drafts_v1. Owner acknowledged;
Task1contracts frozen, P01/commonproof producer cutover/liveguards/compensation/
wire/factories remain unreleased and positive commands unreachable.9h2continues
source/pure only;9gc2UI synthetic only. No concurrent PG owner is authorized.

6ca1Task2discovered a real port gap:an unavailable pre-capture CorrectionScope
did not retain routed case/selected positions for exact later reload. Root chose
a bounded explicit Task1amendment (optionalcase_id/selected_paid_item_ids with
canonicalvalidation/newpuretests),rather than a SQL-private scope subclass.
Historical88-case pure acceptance predates this amendment; fresh independent
review remains required. No source/amount fallback, all-order expansion or
positive refund permission is implied.

6ca1metadata import nowstable enough forrootlegacySQLitecheck:existingadmin
integration4cases first2passed/2setup errors (SQLite cannotparsePG '~' constraint).
RootextendedONLYlegacy_sqlite_tables PG-onlyfamilyexclusion forcorrection/refund/
physicalproof. Same4casesGREEN0.64s, scopedqualityclean; actualPG/productionDDL/
mandatorySQLunchanged. Storageowner retains exclusivePG. Report:
`/tmp/umc-full-sprint-reports/task-6ca1-legacy-sqlite-compatibility.md`.

Root9h2factory check found configuredRedis selected a code store outside the
requiredSQLconfirmation transaction. Newcodes nowalwaysuseexistingSQLrepo;
legacyRedisargument/unrelatedRedis/standaloneadapterretained,no livekeymigration.
FuturependingRedis codesrequire regeneration. ActualRED2fail/3pass→GREEN5,
then54factory/container/service/Rediscarrypassed0.71s; factory26/26statements100%
sysmon@98floor,noexclusions,scopedqualityclean. Rootfrozen3files/report:
`/tmp/umc-full-sprint-reports/task-9h2-factory-report.md`.
This is wiring/pureevidence;9h2actualSQL+wholecoverage/independentreviewpending.

9h2source nowfrozen:362pure passed1.26s,Ruff/format23+mypy16clean. Actualseparate
owner ispreserved; explicitIGconfirmed/linkconflict/unavailable/codeconsumption
versusunconfirmedunavailable distinct; sharedactiveSQLTx/freshsamecode/profile/
postwaitexpiry/narrowattach/5localenoticesimplementedsourceonly. Whole16module
sourcecoverage75.52% remainsFAILED@98 (supplementary0exclusion74.55% alsoFAIL),
actualPG+broadlegacycarrypending. Original9h1reviewer nowreviews9h2source/pure
only; storageowner retainsexclusivePG. All23owned,rootfactory3and9h1tenhashes
verifiedunchanged. No full9h/native/account-resolution acceptance implied.

9h2independent source review402unique purepassed1.39s, all23+3+10hashes matched;
oneImportantportfinding:SQLpreparation wasregistered forsessionlifetime rather
than owningtransaction,so sameAsyncSession reuse couldaccept expiredbarriers.
Currentfreshnormalfactory doesnotcross transactions,buttheportcontract needsfix.
Root returned ONLY bounded lifetimeguard/newtests tooriginalowner,noPG. Bindactual
roottransaction+strongpreparationobject; conservative refusalofenclosingnested
preparation beforelocks isapproved,whilelaterownuniquenesssavepointremainsvalid.
Coverage/actualSQLremainpending; no9h2acceptanceclaimed.

9gc2builder froze7files after201newadmin/162owner/217oldbrowser carrypassed
ononesnapshot;32syntheticblank-secretPNGs. RootactuallyinspectedMAXpublication,
MAXKKdarkobservation andTGreview: archivebranding/literalterms,currentv7/futurev9,
exactmaxmoney,blankproofcontrols andpaid-observation/unapplied/currentunknown
separation arevisible. Freshindependentadmin201+owner162also passed,butoneImportant
auth-lifecycle finding has6TG/MAXrepros:oldhistory/reveal403orowner-onlydetail200
afterselection/formchange ignoresknownpermissionloss andleavesprotectedB/form.
Two disposed-old-bound controls correctlypreservenewcontext. Root returned ONLY
admincontroller/newownedtests forfix; unchangedowner/hooks meansnoautomaticold217
repetition. Independentclosure andwholeP01acceptance remainopen.

Freshgitfetch completed successfully inprimarycheckout:localmain andorigin/main
both6505af277fd01ab83fc7f2ba5ba07eba81bd2396,0newremotecommits afterbaseline.
No checkout/pull/rebase orprimaryuserfilechange wasneeded orperformed.


Fresh bounded freezes after review: 9h2 lifetime fix changes only SQL UserRepository
and its owned fence tests. Strong exact preparation objects are bound to the actual
active root transaction; one bounded end listener clears them, enclosing-savepoint
preparation refuses before reads/locks, later own savepoints preserve root scope.
Final unique pure union413passed/1.36s, scoped quality clean. Changed SQL repository
coverage60.90% remains honestly FAILED at unchanged98floor; actual PostgreSQL and
full16-module gate remain pending. Original reviewer owns source/pure recheck only.

6ca1Task2 builder final scoped gate116passed/37.25s,557/557statements100%, including
new migration at unchanged98floor; Ruff/format11 and mypy5 clean. Dotted --cov
source import/revert duplicated GeoAlchemy2 global event listeners; exact-file
coverage run preserves scope and removes that instrumentation side effect, with
no warning suppression/source workaround. Fresh release verified zero other client
sessions, private schemas and owned processes, disposed engine,11freeze hashes match.
Storage/source plus amended Task1 scope still require independent review. Tasks3–7
remain unreleased; the storage30/25/5 fixture is not full runtime acceptance.


9h2 original independent reviewer closes the transaction-lifetime finding for
bounded source/pure acceptance: exact13-module union413passed/1.45s, all23current
+factory3+Task1ten hashes match, exactlytwo changed files and21unchanged from
pre-fix. Original finding/report preserved; new recheck is
`/tmp/umc-full-sprint-reports/task-9h2-lifetime-independent-review.md`.
No PG/full98 acceptance: correction_storage_review nowowns PG exclusively for
6ca1Task2 independent source/116case recheck.9h2 actualSQL follows explicit release.
The same reviewer nowreviews9h3 intake/collaboration PLAN ONLY, noPG/sourceedit.


Root current static checkpoint on stable source: Ruff allsrc/tests clean, format
893files clean, mypy490sources clean (three existing annotation-unchecked notes),
gitdiffcheck clean. AST graph soleheadfinancial_corrections_a1 parentcampaign_drafts_v1.
Report:`/tmp/umc-full-sprint-reports/task-root-current-static-gate.md`.
NoPG collection/activity; independent storage reviewer retains exclusiveslot.
This does not replace fullmakefix/98coverage or actualdevice acceptance.


9gc2 original reviewer closes the Important auth-lifecycle finding after fresh
independent fulladmin217passed/171.17s; all7freeze hashes unchanged, scopedNode/
Ruff/formatclean. OnlyadminJS+16appendedbrowsercases changed; owner/hooks unchanged
so oldowner162/carry217were not needlessly repeated. Samecurrentbound knownloss
clears allprivate regions/form/reveal/nativeaction beforelocalgenerationfilters;
disposed-oldcontext,404,emptyadminactions andordinaryowner-shapedcommandreceipts
keep the intended behavior. Recheck:`/tmp/umc-full-sprint-reports/task-9gc2-auth-fix-recheck.md`.
BoundedadminUI accepted; fullP01/corrections/actualdevices/bank remain open.

6ca1 independent normal116gate passed38.81s but twoImportant findings reproduced
separately: pending branch acceptedcapture_intent instead ofactualclientcapture;
empty-selected observationroute skipped bothprospective-scope rereads. Fullreport
`/tmp/umc-full-sprint-reports/task-6ca1-storage-independent-review.md`. Reviewer
releasedPG freshzeroresources/14hashesunchanged. Root returned ONLYguard/scope
reread+ownedpermanentregressions tooriginalowner with exclusivePG; noTasks3–7.
9h2owner maywrite newSQLtestsourceONLY, with noPGcollection/engine/schema until
explicitlatergrant; all16runtime+factory3+9h1ten remainfrozen.


9h3 independent plan review ready after fullsix-field sourceidentity/reentrant
expecteditemonly/root-lifetime clarification. Root released ONLYsource/pureTasks1–2
to native_intake_collaboration (8namedruntimefiles, optionalfocusederrors, owned
pure/API tests/fakes). Root owns centralAPI2resolverinjections. NoPGgrant; correction
fixowner retainsexclusivePG.9h2owner canprepareSQLtestsourceONLY;9h1/payout/factory
frozenfiles preserved. No wholecaller/SQL/98acceptance follows this planning review.


Root completed exactly two central 9h3 injections after the source owner confirmed
the typed router contract: intake and collaboration now receive the existing
resolve_financial_principal. All other routers and the generic resolver are
unchanged. Scoped api.py Ruff, format and mypy passed. The source owner will
include relevant actual-app carry once service/repository preparation is stable;
no actual SQL or whole-tree acceptance is inferred from the wiring check.

A read-only snapshot addendum in task-9h3-source-map.md now records the exact
partner_view, selection_view and campaign_summary interfaces and first-User-query
seams. Their future native checks must occur inside the same RR READ ONLY
snapshot before private subqueries, with no writer locks or account creation.
No next-snapshot implementation or PostgreSQL grant follows that inventory.


6ca1 bounded storage fix is frozen for independent closure: eight permanent
regressions added, fresh complete gate124passed/39.35s and561/561statements100%
at unchanged98floor, scoped quality clean. The actual capture event is checked
in every application branch; empty selected routes remain unavailable but now
fingerprint/reread actual case/request/order/capture and complete lock scope.
A real two-PID after-barrier manager change refuses without a late User. Only
five authorized files changed; nine other frozen files match. Builder released
PG with fresh zero resources and14hashes checked. Original reviewer now owns PG
exclusively for the124case/finding closure; other owners remain non-PG.
Report:`/tmp/umc-full-sprint-reports/task-6ca1-storage-fixes-report.md`.
Tasks3–7 and full30/25/5runtime remain unreleased/unaccepted.


The first6ca1 fix recheck passed124cases/40.66s and the two original reproductions
now pass. Capture-event finding is closed; scope finding remains OPEN: nullable
early-case client_id raises TypeError, and a case-only report with a later request
returns at missing order before fingerprinting that request. Two bounded normal
edge tests reproduced these failures; sources unchanged. Reviewer released PG
fresh at01:52:56UTC with zero resources and14hashes unchanged. Root will return
these two residuals to the original owner within the existing scope finding.

Root wrote a plan-only next snapshot slice:
`docs/superpowers/plans/2026-10-24-umc-native-read-snapshots.md`. It preserves
partner/selection/summary RR READ ONLY semantics and validates native proof at
each first snapshot User query. Independent feasibility review and active9h3
error-wrapper ownership freeze remain prerequisites; no source/PG release.


9h3 source owner froze ten runtime modules, four owned tests and root's central
API hash separately. Fresh99focused/284selected pure tests pass; Ruff15files and
mypy11sources pass. Correct exact-file sysmon statement metric is57.12%
(1247/2183), including the entire central API; unchanged98floor correctly fails.
A separate C-tracer line/branch report is supplementary only. Dotted-source
registration-warning measurement is preserved as historical, superseded by the
warning-free correctly instrumented run. Actual SQL remains unexecuted.
Report:`/tmp/umc-full-sprint-reports/task-9h3-source-report.md`.
A fresh independent source reviewer now checks the fifteen frozen files and
reruns the exact284pure selection, with no PG. Correction residual-fix owner
retains exclusive PG;9h2's two SQLtest files are ready but have no execution grant.


6ca1 second scope-fix freeze:132passed/42.32s,562/562statements100%, scoped
quality clean. Eight matrix cases captured RED6failed/2passed before the minimal
three-file fix; nullable client remains genuinely absent, retained requests now
affect fingerprint before the missing-order return. Capture/schema and eleven
other frozen hashes unchanged. Resource-zero PG release is recorded; original
reviewer now owns exclusive PG for current132case closure. No runtime refund
producer or Tasks3–7 release follows this builder checkpoint.


6ca1 Task2 storage/source and narrow Task1 amendment are independently ACCEPTED.
Final132gate43.35s plus all four original/residual probes7.02s passed;14hashes
unchanged. Capture and complete-scope findings are closed. No Tasks3–7 or fullAC9.
Fresh zero-resource PG release confirmed; root granted exclusive PG to9h2 owner
for its prepared normal SQL regressions and full unchanged98 scoped gate.

9h3 independent284pure passed, but one Important error-boundary finding remains:
recognized HTTPException details reflect arbitrary status200/418/500. Request-invalid
normalization already works. Root released ONLY native_caller_errors.py and owned
API regression tests to original owner, source/pure only. Preserve exact permitted
404 status versus409 command semantics and no-store; no payout wrapper refactor.
Other native/source/factory hashes remain frozen.


9h2 final builder SQL gate is GREEN and frozen:5574passed/1unrelated global
DATABASE_URL migration skip/12preserved legacy warnings; all209 mandatory
privatePG cases passed. Actual42distinctPID pairs,37observed waits and2real23505
savepoint cases. Fresh17whole-module statement coverage2235/2274=98.28496%
at unchanged98floor;36existing baseline exclusions enumerated, no new omit.
Runtime23/factory3/Task1ten preserved. SQL3files freeze includes fixture uuid5
handle correction and the intentional old messenger expectation amendment with
a separate committed-remap challenge-authority regression. Source report is
`/tmp/umc-full-sprint-reports/task-9h2-sql-report.md`. Fresh zero-resource PG
release confirmed; original reviewer now owns PG exclusively for independent
209case/source/PID verification. Full9h and whole-tree acceptance remain open.

9h3 exact-status finding is independently CLOSED:312unique pure tests and all
30ASGI desired scenarios pass;15+10+3+23hashes match. Only wrapper/API test changed;
wrapper46/46statements100%@98floor, full11-module aggregate/SQL still pending.
Report:`/tmp/umc-full-sprint-reports/task-9h3-status-fix-independent-review.md`.
Owner now prepares Task3 SQLtest SOURCE ONLY, noPGcollection/connection/engine.
Runtime15entry freeze is retained pending actual SQL; old corresponding PG
resolver fixtures may receive narrowly documented typed-proof compatibility fixes.

Task3 physical-proof plan review is ready with recorded prerequisites: same
producer+execution ownership, actual historical command attribution, unavailable
never unused, common canonical-key mutex, claim before money savepoint without
requiring not-yet-inserted command/outcome, and actual observed-account mapping.
Root released DORMANT6ca1Task3a source/pure only to original correction owner:
new physical_proofs repo, blank optional source setting, two constant-text port
exceptions and two new pure/config test files. No P01/schema/oldfixture edits or
PG allowed. Accepted pure port gains only these explicit exception additions;
historical Task2 freeze is not silently rewritten. Task3b awaits9h2 independent
SQL/preservation and a separately coordinated PG grant.

9h4 snapshot plan review is ready after the nonblocking PID-boundary clarification:
no earlier SELECT may establish the snapshot before the actor query. Source is
not released; active9h3 frozen wrapper/centralAPI ownership and its pendingSQL
preservation remain coordinated prerequisites.


Fresh9h2 independent SQL acceptance:209passed20.04s,42distinctPID pairs,
37observed waits,2real23505cases, all39frozen entries preserved. No remaining
Critical/Important finding. Builder5574/98.28496% remains attributed; independent
broad/coverage repetition was unnecessary. Resource-zero release verified at
02:19:57UTC. Root now grants9h3 owner exclusive PG for approved Task3 as ordinary
permanent tests become ready; no other PG access. Source15entry status-fix freeze
stays unchanged unless a concrete runtime issue is coordinated.

M02 Task10b2 sealed-submit/moderation/quota/jobs implementation PLAN ONLY is
now assigned to a fresh source/design worker. It reads accepted10a/10b1 and
actual current campaign contexts; no implementation, migration or PG action.
No source/destination export, invented quota/pricing or send enablement.


### Root checkpoint: analysis refresh after accepted 9h2 SQL

Fresh `git fetch origin` succeeded; primary `main` and `origin/main` remain at `6505af277fd01ab83fc7f2ba5ba07eba81bd2396` with zero divergence. User workspace changes remain untouched. The analysis canvas now removes outdated open claims for accepted MAX→TG linking and 9h2 SQL, distinguishes accepted payout readers/UI from remaining corrections, and states that all 24 archive files already match the feature worktree. Status totals stay 20 tasks (2 locally confirmed, 15 partial, 3 not implemented) and 30 criteria (14 locally confirmed, 13 partial, 3 not passed). Inline JSON and unique IDs were checked; no render/TypeScript verification is claimed. Evidence: `/tmp/umc-full-sprint-reports/task-root-analysis-refresh.json`.

9h3 remains the sole PostgreSQL owner. Its first bounded source-frozen permanent SQL group has reported 61 passing tests; this is an intermediate builder result, not stage acceptance or a coverage result. 6ca1 Task3a remains dormant source/pure only. 10b2 planning separates a reviewable backend moderation slice from the required later owner/moderator and recipient UI; no sender may be enabled before the actual destination UI exists. The active full-document goal is not complete.


### Root checkpoint: dormant proof source and campaign moderation plan review

6ca1 Task3a is frozen for fresh independent source/pure review: 127 pure/config tests passed and scoped quality checks passed. Its honest whole-module coverage is 438/477 statements (91.82%); the unchanged 98% gate FAILED and remains pending actual SQL integration. The adapter is dormant, P01 and shared fixtures were not changed, and no PG slot was used. Source report and five-file freeze are `/tmp/umc-full-sprint-reports/task-6ca1-proof-source-report.md` and `task-6ca1-proof-source-freeze.json`. Task3b is still unreleased even though the prior 9h2 source-preservation prerequisite is now accepted.

The backend-only 10b2 plan is frozen at SHA-256 `8c892cdd74a0f493dfdff6d02e3d5ae1deb884bf8db9119290817d0ce947bb36` and is under fresh independent planning review. Its required later owner/moderator UI, recipient screen, worker/outcomes/responses and reports remain open. It grants no source, schema, PG or runtime activation. 9h3 retains the only PG grant and unchanged runtime freeze; root additionally requested a small real main-router TG/MAX integration carry for its two production resolver injections.


### Root checkpoint: 6ca1 Task3a bounded source/pure review

Read `/tmp/umc-full-sprint-reports/task-6ca1-proof-source-independent-review.md`: fresh 127 pure/config tests passed; Ruff/format on five files and mypy on three modules passed; five source hashes and thirteen preserved Task2 hashes matched. No Critical/Important source/pure findings. Root accepts only the dormant source/pure boundary. Whole-module coverage remains 438/477 (91.82%), explicitly FAILED at the unchanged 98% floor, with actual SQL/cutover still pending. Task3b, positive refund runtime and full Task3 remain unreleased.

Independent 10b2 planning review found one Important preflight ordering gap: an over-cap refusal could precede current native validation and prevent same-key replay after audience growth. The plan author is correcting only the plan/report, including both regressions; no implementation grant followed. 9h3 retains exclusive PG and its runtime freeze. A separate read-only consistency check now reviews the analysis canvas for stale material claims.


### Root release: 10b2 Task1 dormant contracts/principal source only

The corrected plan `docs/superpowers/plans/2026-10-24-umc-campaign-10b2.md`, SHA-256 `eecf783cf4ae3168d985e27df8a646df9b24579ea86ae51e94ab9b950d517654`, is ready for a bounded source release after `/tmp/umc-full-sprint-reports/task-10b2-plan-fix-independent-review.md` closed its one Important ordering issue. Root releases only new standalone contracts, templates and the unmounted principal adapter: `domain/campaign_moderation.py`, `application/campaign_moderation_ports.py`, `application/campaign_message_templates.py`, `miniapp/campaign_principal.py`, and new unit files `tests/unit/test_campaign_moderation_contracts.py` and `tests/unit/test_campaign_principal.py`. A new `domain/campaign_capacity.py` is allowed only if immutable capacity records genuinely need their planned own module now; capacity service/SQL accounting remains unreleased. Do not add unused placeholder implementations to satisfy future names.

This is the dormant source/pure portion of Task1, not full Task1 acceptance. Existing campaign services/ports/routers/repositories, shared helpers/tests, root factories/types/API/metadata, configuration, schema/migrations and every other frozen source file remain untouched. No router mount, runtime caller, dispatcher registration, live send or flag is installed. Source and meaningful pure tests may use declared synthetic facts only; no HMAC/SQL/concurrency acceptance follows. Test actual strict types, sealed hash/envelope/locale boundaries, immutable accepted revision semantics and constant canonical failure translation without reflecting arbitrary status/text. Record RED/GREEN and honest whole-module sysmon measurement at unchanged98, including every changed executable module and no new excludes. Freeze/report before fresh independent review.

9h3 remains the exclusive PG owner. Its gate cohort `/tmp/umc-full-sprint-reports/task-9h3-sql-gate-cohort.json` is an explicit 38-file list excluding these new files and measures the 11 frozen runtime modules. No existing cohort file may be changed by this release. Task1 source work cannot collect PG, construct engines, inspect credentials, alter accepted schemas/head, commit, push, activate or deploy. This release grants neither later Task1 integration nor Task2–6 source/schema/PG work.

### Root analysis consistency corrections

Applied the exact material corrections from `/tmp/umc-full-sprint-reports/task-analysis-consistency-review.md`: AC19 now records accepted 9f linking while keeping full user acceptance open; R04 records actual legacy-feedback summary integration without treating it as v1 success/money; L01 distinguishes implemented technical document acceptance from missing real legal/accountant decisions. R05 also records the dormant proof source checkpoint and explicitly failed91.82% coverage gate. Inline JSON/unique IDs and unchanged20/30 status totals were checked. Evidence: `task-root-analysis-consistency-applied.json`; no render/TypeScript claim.


### Root checkpoint: active 9h3 exact coverage target and next proof cutover

9h3 builder completed 123 new actual PostgreSQL cases (including four mounted production-router TG/MAX intake/work checks) and 185 relevant PG carry cases. The fixed38-file broad run passed883 but covered2130/2187 statements (97.39%), below98. The explicit40-file extension passed917 and covered2133/2187 (97.53%); unchanged Coverage default precision reported98 and its configured gate exited0, but root requires the exact98 target before acceptance. Both fractions/configured results remain explicit. No threshold, precision, exclusions or runtime source changed. Root approved meaningful additional permanent cases only in the new owned PG test file: actual signed mounted rating create/read with installed SQL services, persisted actor/role/data, duplicate409, missing-order404 and nonparty403 compatibility controls. With2187 statements, exact98 needs at least2144 covered. Stage acceptance, independent review and PG release remain pending; the sole owner is still native_intake_collaboration.

The read-only next proof-cutover map is `/tmp/umc-full-sprint-reports/task-6ca1-proof-cutover-preflight.md`; root read it and found no new interface blocker. P01 source/PG release is still held until the native preservation handoff. Before any cutover edit, preserve a portable auditable actual pre-cutover producer or proven golden fixture with exact provenance/hash so a fresh independent run can reproduce historical settled/unapplied facts; no dependence on temporary process state or invented owner IDs. Source release will later cover writer/repo/factory, read-start readiness/error set and explicitly synthetic positive fixture settings. No new schema is needed for the accepted claim table.


### Root handoff and release: 9h3 independent PG; 9h4 snapshot core source

Root inspected `task-9h3-sql-report.md`, final exact2160/2187 statement gate, and `task-9h3-sql-pg-release.json` with fresh zero resources. Exclusive PG transferred to `native_caller_sql_independent_review`, which must verify the actual combined two-file `task-9h3-pg-freeze-sha256.json` plus15-entry status-fix freeze and preservation10+3+23 before one fresh exact40-file/11-module gate. The anticipated alternate manifest name in the initial handoff was corrected; no file rename is required. Final builder919 includes698 pure/API and221 PG (125new plus96existing); earlier185 overlaps and is not added. Builder source is unchanged and bounded acceptance remains pending independent review.

Root re-read the accepted 9h4 snapshot plan and independent feasibility review. Release its SOURCE/PURE CORE ONLY now: the three partner/selection/summary ports, three corresponding services and three SQL read repositories from `2026-10-24-umc-native-read-snapshots.md`; new `tests/application/services/test_native_snapshot_views.py`, and only corresponding existing pure view fake/signature expectations outside the fixed9h3 cohort if needed. Preserve optional trusted internal compatibility and current session ownership. Native columns must be compared at the existing first actor SELECT inside that same RR READ ONLY snapshot, before private reads. No row/advisory locks, DML/autoflush/wallet/account/country creation, snapshot restart or separate current connection.

All three API routers, `native_caller_errors.py`, `miniapp/api.py`, every9h3 frozen source/test/cohort file, root factories, schemas and migrations remain HELD until independent9h3 closure and a later explicit extension. No current route is mounted or rewired by this core release. New API or PG test execution/collection, engine construction/private routing/credential inspection and any PG query remain forbidden. Optional new PG test source preparation is not granted here. Capture meaningful core RED/GREEN and honest explicit whole changed-module sysmon98 evidence without new exclusions; SQL-dependent gaps may remain pending, never fake SQL acceptance. Report the core checkpoint before broader source work. The same implementation owner is reused with no PG authority.


### Root acceptance and releases after independent 9h3 closure

Root read `task-9h3-sql-independent-review.md`: bounded source/SQL accepted with no Critical/Important issue; fresh919=125newPG+96oldPG+698pure/API, zero skips, exact2160/2187=98.765432%,70actualwaits/72distinctPIDpairs,17+10+3+23 hashes preserved and quality17 clean. Root also read the independent02:58:34UTC fresh zero-resource PG release. The bounded native-caller plan checkboxes are complete; the broader native caller plan remains open. Historical freezes remain intact and may be intentionally superseded only by the new exact releases below.

**9h4 source extension, NO PG:** after its core checkpoint, the same owner may finish Tasks1–2 of the accepted snapshot plan, including the three owned API routers, new unit native_snapshot_api tests and corresponding pure API fakes. Add only NoStorePartnerRoute/SelectionRoute/SummaryRoute with separate exact code/status maps to `native_caller_errors.py`; preserve the accepted intake/collaboration maps/base behavior and carry its312 pure cases. This explicitly supersedes only that wrapper's historical9h3 hash. Root owns the three central resolver injections and will apply them once typed routers are ready, intentionally superseding the old root-api hash. Every other9h3 source/test remains frozen unless a concrete compatibility change is separately coordinated. No SQL collection/engine/routing/credential use, prepared PG test source, schema/migration or global resolver change is granted. Preserve full same-snapshot read rules and honest whole changed-module98 gate; report final source freeze before PG.

**6ca1 Task3b source + EXCLUSIVE PG release:** owner `corrections_a1_contracts` may implement only the accepted proof cutover. Root verified by static AST the sole migration head `financial_corrections_a1`, actual parent `campaign_drafts_v1`, and all three staged pre-cutover producer hashes still match (`task-6ca1-proof-cutover-root-release-check.json`). No new migration/schema/model change is granted. Use only isolated private UUID financial/legacy fixtures and this exact existing head; the old-parent cutover fixture may upgrade from actual campaign_drafts_v1 to financial_corrections_a1. Credentials stay inside runner processes and never appear in output. The independent native reviewer has released all PG resources; no other owner may collect/query PG until this owner later releases it.

Exact Task3b source map: payout_service.py, repositories/payouts.py, container/payout_factory.py, payout_view_service.py, application/payout_errors.py; integrate the accepted physical_proofs.py and amend it only for concrete actual-SQL defects while preserving accepted DTO/key/success contracts. Config, proof ports, financial/native command contracts, schemas/migrations, UI, root API/factories and unrelated sources remain frozen. New tests/postgres_financial/test_physical_proof_cutover.py, tests/helpers/physical_proofs.py and an auditable portable tests/fixtures/physical_proofs/ producer or golden-fact fixture are allowed. Narrow existing changes: PG payout_runtime/recovery/defensive/history_readiness/views, unit payout_view_service/error_privacy, and only explicit synthetic source settings in corresponding released positive fixtures. Other fixture changes require a concrete compatibility finding, never assertion weakening.

Preserve a fresh-run reproducible actual pre-companion settled and successful-unapplied producer fixture BEFORE changing source; staged bytes/hashes are at `/tmp/umc-full-sprint-reports/task-6ca1-pre-cutover-producer-source/`. This staging is not SQL proof or permanent fixture acceptance. Same command hashes/receipts/ciphertext and actual historical attribution must survive the actual upgrade with no fake/backfilled claim UUIDs. Preallocate command ID only after replay misses and before dispatch, outside economic hashes; allocate real outcome ID and claim the recognized proof outside the money savepoint before the observation identifies itself as history. Same producer/execution returns its original owner; foreign/multiple owners conflict without reassignment. Retain actual observations and proof on expected economic refusal; unexpected database/outer failures remain atomic. Missing/invalid source denies writer start and read-start hint with an exact safe code while independent observation remains available. No positive refund ingress/application, correction guard/consumer, transport or flag activation is released.

Run meaningful RED/GREEN actual cutover/provenance, both reuse orders/shared-mutex races across distinct PIDs, same-intent reconciliation, savepoint retention/outer rollback, missing-source readiness and historical/changed P01 carry. Include accepted pure proof/config/contracts and current native financial/payout readers/API regressions. Measure all changed executable modules honestly at exact98 with single-package or explicit whole-file coverage (never multiple dotted --cov sources), no new excludes/floor/precision change; scoped quality and final hashes/report. Root retains whole makefix/commit/release. Stop after a final freeze and fresh zero-resource PG release for independent review. 9h4 remains source-only; new campaign contracts are outside this PG grant.


### Root acceptance and release: dormant campaign service source

Root read `task-10b2-contract-independent-review.md`: no Critical/Important source/pure finding, fresh134 tests, exact351/356=98.5955056%, zero exclusions, quality6/4 and all17 reviewed paths unchanged at review time. Its explicit-file single-run measurement supersedes the builder's historical multiple-dotted-source measurement form. Root accepts only the dormant six-file Task1 source/pure portion. The accepted plan hash remains eecf783cf4ae3168d985e27df8a646df9b24579ea86ae51e94ab9b950d517654; full Task1 integration, SQL and M02 remain open.

Release coherent SOURCE/PURE versions of Tasks2–4 to the same campaign owner, keeping the runtime unmounted: NEW domain/campaign_capacity.py; NEW services/campaign_eligibility.py, campaign_submission_service.py, campaign_moderation_service.py, campaign_capacity_service.py; expand application/campaign_moderation_ports.py with the actual needed immutable records and Protocol methods. Existing accepted command/revision/seal/context/hash semantics remain preserved; domain/campaign_moderation.py may receive only required additive helpers/records, with old pure regression carry unchanged. Refactor only existing campaign_audience_service.py to call the same shared eligibility implementation, preserving exact accepted preview output/fingerprint/unknown-metric/consent/dedup semantics. Do not create a second weaker predicate or hypothetical successful-metric producer.

NEW tests/unit/test_campaign_submission_service.py, test_campaign_moderation_service.py, test_campaign_capacity_service.py are allowed; extend the owned new moderation-contract file only for additive source records. Corresponding existing pure audience/preview tests may receive narrow fixture/signature updates only if needed and without weakening assertions. No existing draft lifecycle service/repository, campaign_review_ports.py, router, factory/type/root API/config, SQL adapter, schema/model/migration or other source is released. Missing not-yet-installed capacity/context/persistence capability must be unavailable, never a no-op positive fallback. The new service graph is not imported by existing runtime.

Implement actual planned source logic and dependency interfaces: complete provisional preflight then prepared current native/action authority and receipt before new admission; shared exact epoch-consenting own audience; full five-locale immutable seal; exact distinct-admin surviving subset/context and atomic intended review/member/jobs writes; actual LIMIT_NAMES/cross-publication usage/reservation/cooldown decisions with explicit bounded expiry progress. All mutations remain in the supplied caller transaction; no internal commit/session/ambient context. Pure fakes are declared synthetic and cannot establish actual SQL barriers, ownership/provenance/locks/atomicity, provider metrics or migration acceptance. Preserve corrected remap-over-cap and replay-after-growth ordering cases in the pure source trace; later actual PG remains mandatory.

Do meaningful RED/GREEN by owning service, then one coherent explicit-file whole changed-module sysmon gate at exact98, no new exclusions/precision/floor changes, no multiple dotted coverage sources, and scoped quality. Record phase boundaries and freeze/report; no new blanket plan/approval loop is required for routine choices within this reviewed design. PG belongs exclusively to corrections_a1_contracts; this source owner cannot collect PG, create engines/read credentials or prepare schema/migrations. All source/PG/root integration/UI/worker/outcome/report completion claims remain bounded and no message/send/flag/commit/deploy is granted.


### Root implementation: typed snapshot main-router wiring

Applied exactly three resolver argument switches for partner/view, selection and campaign-summary to existing resolve_financial_principal. Reversing only those arguments restores the accepted9h3 rootAPI hash5a33900705ac1a8f2f584be6d7c3042fb6ff542cf725f1074025f72518a71311; no other rootAPI edit occurred. New tests/unit/test_native_snapshot_wiring.py mounts the actual main router for both signed hosts and exercises typed existing-account forwarding, unknown-account refusal/no registration and a declared synthetic view-native denial. A corrected role fake supports both legacy keyword and typed positional calls; the initial fixture issue is preserved separately. Behavioral RED18 failures (old UUID resolver produced401 for known-account success) became GREEN18 in0.88s after only the three switches. Ruff/check-format two files and mypy rootAPI pass. Current hashes and explicit pure/MVCC boundary are in `/tmp/umc-full-sprint-reports/task-9h4-root-wiring.json`. The current API hash intentionally supersedes the historical9h3 freeze; no SQL acceptance follows.

The9h4 source owner may run the two unchanged historical Container SQLite-memory cases and the existing previously deselected SQLite guard as a narrow source-carry exception. This grants no PG/routing/credential access. Expected combined source cohort602 is not yet a verified count; source14-module coverage remains to be measured honestly.


### Root acceptance and preparation release: 9h4 source freeze

Root read `task-9h4-source-independent-review.md`: source/pure boundary ready with no Critical/Important issue; fresh602 pass/no skips, quality20 clean, all20 frozen hashes matched. Accept only source/pure readiness. The unchanged whole14-module98 gate explicitly FAILED at754/1736=43.4331797%, zero exclusions; actual SQL/MVCC/broad carry remain pending. The accepted old wrapper prefix and three intentional root argument changes remain explicitly preserved. No full9h4/native/sprint acceptance follows.

Release PREPARED PostgreSQL TEST SOURCE ONLY to the same9h4 owner: NEW tests/postgres_financial/test_native_snapshot_views_pg.py and tests/helpers/native_snapshot_pg.py. Read existing partner_view_api, selection_view_api and campaign_summary PG fixture source; no old PG file edits yet. Build ordinary permanent mapping-first/snapshot-first signed TG/MAX cases for all three families using installed Container/main router, actual repositories/TM and existing real source producers. Prepare actual status/role/membership/foreign/unknown/no-country, no private reads before denial, coherent snapshot-first facts, and no DML/locks/initialization assertions. No SQL-result mocks or fake session capability may supply eventual PG evidence. Driver metadata or the actual actor query must supply PID without an earlier SELECT establishing the snapshot; transaction settings are inspected only after that intended first query. Fixture setup and actor/native/source writes belong only to future isolated test execution.

This source preparation grants NO module import/pytest collection, engine construction, routing/credential inspection, database connection/query, schema/migration, runtime/helper/source/frozen20-file edit or test execution. Only AST/compile without imports and scoped new-file Ruff are allowed. Existing PG fixture/native compatibility adjustments may be proposed in the prepared report but remain unedited until the actual PG grant. Freeze both new paths and report exact case/fixture map to root; no complete98 or MVCC acceptance. PG remains exclusively with corrections_a1_contracts for its current cutover gate and later fresh independent review; source readiness or a visible head grants no access.

### Root coordination: isolated legacy payout API fixture

The complete 3b cohort now reproduces one test-isolation failure after more than 100 earlier genuine requests fill the existing global ascending queue. Its standalone carry passes; production pagination and all API assertions must remain unchanged. Root inspected the shared real PostgreSQL fixture and the API module. Extend the current 3b grant only to `tests/postgres_financial/test_payout_api_postgres.py`: add a module-scoped local `financial_pg_engine` fixture that delegates to the existing financial fixture generator, retaining its exact URL checks, current-head migrations and teardown. This gives the API module its own private schema without changing the shared session fixture or hiding the problem through ordering. No production source, assertion, queue limit, schema or unrelated fixture change is granted. Preserve the initial complete-run evidence (771/2 and 772/1, exact1398/1412); rerun the identical complete cohort after this bounded fixture repair. The same owner retains exclusive PG until its final fresh zero-resource handoff.

Root also corrected two stale 9h3-pending sentences in the analysis canvas (S01 and its next-result paragraph). Both now agree with the accepted independent 919/exact98.765432% result and keep 9h4 SQL pending. Inline JSON, unique IDs and unchanged 20/30 status totals were checked; no TypeScript or render verification is claimed. Evidence: `/tmp/umc-full-sprint-reports/task-root-analysis-9h3-consistency.json`.

### Root handoff: dormant campaign service source review

Root read the frozen `task-10b2-service-source-report.md`: builder234 pure tests, exact1014/1021=99.3143976% across seven whole runtime modules, zero exclusions, scoped quality11/7 clean. The manifest `task-10b2-service-source-freeze.json` hashes to `3ac55b2d0d2db294eae61e7baac13a9ee94ee4060df3a2426c3ac2135766627a`. These results remain builder-attributed pending fresh independent source/pure review. The author stopped; no SQL, integration or later campaign work is released. A fresh reviewer may read the released source and run the exact pure eight-file cohort and whole seven-file coverage with unchanged98. Verify preserved preview/accepted Task1 semantics and source hashes before and after. No PostgreSQL, engine, private routing/credential, schema, source mutation or runtime activation is granted. A new ordinary pure reproduction file is allowed only for a concrete finding; do not alter frozen tests to obtain green.

### Root handoff: physical-proof cutover independent SQL review

Root read `task-6ca1-proof-cutover-report.md`, its 34-file `task-6ca1-proof-cutover-freeze.json`, the final coverage JSON and fresh03:40:37UTC zero-resource release. Builder773 passed in289.42s; exact1399/1412=99.0793201% across eight whole runtime files plus the portable helper, with eight pre-existing configured exclusions explicitly enumerated and no new omission. Quality17/8 clean. Initial fixture failures and the post-cutover archival baseline experiment remain separate historical evidence. The author stopped. Independent acceptance is pending.

Transfer EXCLUSIVE PG to the fresh `physical_proof_cutover_independent_review` owner only. Read and verify the full freeze, portable actual producer provenance, prior Task2/Task3a preservation and approved Task3b source map. Run the identical permanent31-file cohort with one fresh explicit-whole-file sysmon trace at exact98, verify current native and both proof-mutex PID/wait evidence, source quality and hashes before/after. Only isolated private UUID financial/legacy schemas at the already accepted head are allowed; the genuine historical fixture may start at actual campaign_drafts_v1 before its actual upgrade. No source/schema/migration/fixture edits, live facts, flag, commit or activation. A permanent new reproduction is allowed only for a concrete finding. The report must distinguish source/storage authority from the still absent refund runtime and must end with a fresh zero-resource release. 9h4 remains prepared-source-only until that handoff is complete.

### Root coordination: campaign source review corrections

Root read `task-10b2-service-source-independent-review.md`: two Important findings, no Critical. Fresh234 and exact1014/1021 remain green but four ordinary permanent reproductions fail. The service permits a valid same-version current revision that differs from its immutable seal, mixing new content/job digest with the old envelope. It also applies approval-only enabled-policy/current-grant gates before safe admin rejection, contrary to the accepted Task4 cleanup rule. All frozen hashes matched; the reviewer stopped after adding only the authorized reproduction file.

Return this narrow SOURCE/PURE correction to the original campaign author: edit only `services/campaign_moderation_service.py` and its owned `tests/unit/test_campaign_moderation_service.py`. Preserve the reviewer's four-case `test_campaign_service_source_review_repro.py` byte-for-byte. Refuse any exact retained current revision/campaign/owner inconsistency before detail, screening, subset use or decision effects. Separate approval eligibility from fresh-context safe terminal rejection while retaining current native proof, active distinct-admin authority, exact submission/context, receipt-first ordering and no jobs/new reservations on rejection. Approval must still deny suspended/revoked/changed authority. Add meaningful negative approval and positive cleanup cases without allowing stale contexts or missing required source facts. Existing five-locale sealing, preview and other six modules remain frozen; coordinate only a concrete necessary interface change, not a wider refactor.

Keep the initial builder/reviewer reports and freeze as history. Run the exact prior eight-file cohort plus the unchanged four reproductions and new owned regression cases under one same-seven-whole-module sysmon trace at exact98; no omissions, floor, precision or exclusion change. Finish scoped quality, new `task-10b2-service-fix-report.md` and `task-10b2-service-fix-freeze.json`, then stop for a fresh fix review. No SQL, engine, credential/routing, schema, root integration, UI, worker or send work is released. The bank independent reviewer remains the sole PG owner.

The author identified one contradiction in the review reproduction: its approval branch required the already-inconsistent detail call to succeed before entering the expected-refusal block, while the detail branch correctly required early refusal. Root confirmed it, preserved the exact original bytes/SHA in `task-10b2-service-source-review-repro-original.py.source`, and moved only that detail call inside the existing expected-refusal block. Every assertion is AST-identical; separate owned direct-approval regression remains required. This explicitly supersedes only the reproduction hash from `43d934fd3178576e39292fe3da1f959dc20a16a16037a5dab2a5938bb01a40fe` to `8a02ff7b7034b4782c850101ea060ebee8ac8ec3a85125ea3b42cdc66e7139d3`; preserve the corrected bytes afterward. Root ran AST/compile and Ruff/check-format only, not tests against concurrently changing source. Evidence: `task-10b2-service-review-repro-root-correction.json`. Initial four RED artifacts remain unchanged and the fix still needs fresh complete verification.

### Root acceptance: common physical proof authority and P01 cutover

Read `task-6ca1-proof-cutover-independent-review.md` and its independent03:49:41UTC release: fresh773 passed in288.07s, exact1399/1412=99.0793201%, quality17/8 clean,34 frozen hashes matched, no Critical/Important finding. Both proof ownership orders produced actual distinct-PID waits;54 native carry cases completed. Exact archived real producers and actual parent-to-current migration prove historical attribution without fabricated owner IDs. Eight existing configured excluded lines remain explicit. Accept bounded Task3/P01 integration, including closure of the earlier pending Task3a SQL coverage gate (470/477=98.5324948%). No positive refund application, guard, compensation consumer, signed correction ingress, fullAC9 or whole-project gate follows. All independent runners and engines ended; zero other sessions/private schemas/owned processes. PG is free pending the separately checked prepared9h4 handoff.

### Root release: correction Task4 dormant source/pure

Release SOURCE/PURE Task4 to the original correction owner: NEW `application/services/correction_service.py`; extend `application/correction_ports.py` only with actual required immutable trusted records/Protocol methods/helpers while preserving existing command DTOs, validation, hashes and source-scope meaning; extend `infrastructure/db/repositories/corrections.py` only for actual Task4 actor/native authority, immutable fact loading/persistence and bounded own/admin reads. Preserve accepted scope discovery/ordered barriers, replay/projection integrity and schema semantics. NEW `tests/application/services/test_correction_service.py` and, only if needed, NEW `tests/helpers/correction_commands.py` for explicitly synthetic pure facts are allowed. Narrow additive cases in owned `test_correction_contracts.py` may pin newly required helpers without weakening existing assertions. No existing schema/model/migration, domain/physical-proof/P01 source, factory, root API, UI or unrelated test change is released. This intentionally supersedes only the old port/repository and explicitly additive owned-contract-test hashes after completed Task3 preservation.

Implement the accepted own request/current active-admin review/manual observation/fresh exact match orchestration in the supplied caller transaction. Current native/role/ownership checks precede private output, replay and privileged writes under the existing complete sorted User/wallet scope; no actor-only prelock or late User acquisition. Original receipts remain immutable and separate fresh status is explicit. Preserve exact captured full-selection bundle and source/due evidence. Real observations and recognized original claims survive expected economic refusal outside the savepoint; unexpected database/outer failure propagates. Missing Task6 compensation may persist an exact reviewed match awaiting assessment only, never a no-op positive application. No capture arrival auto-matches, updates old nullable facts, or invents client request/approval/owner IDs.

Before settling the early-observation interfaces, explicitly map the existing immutable nullable early intent/observation to a later fresh approved bundle/match and stable physical owner, including actual FK/deferred-guard relations. If the accepted schema cannot represent that path, report the concrete relation gap and proposed additive correction; do not silently alter schema, reassign a proof or invent historical linkage. Proceed with independent authorized Task4 work while resolving that concrete compatibility issue. Source/pure evidence does not prove real capture provenance or SQL retention. Keep all changed executable modules in honest whole-file sysmon measurement at unchanged exact98, reporting SQL-dependent failures as pending rather than mocking SQL. Meaningful RED/GREEN, scoped quality and final source freeze/report are required before actual SQL. No imports/collection of PG tests, engine, credential/routing/database/query/schema activity, runtime factory/ingress, compensation, forward guard, message, flag, commit or deployment is granted. 9h4 remains source preparation only until root checks its frozen files and grants the free PG slot.

### Root release: 9h4 actual PostgreSQL snapshot verification

Root read `task-9h4-pg-prepared-report.md` and both complete prepared files, and statically reverified all22 source/prepared hashes and the sole `financial_corrections_a1` head with parent `campaign_drafts_v1` in `task-9h4-root-pg-release-check.json`. The14 functions/110 expected cases and52 intended two-PID boundaries are preparation counts only. Root already read the independent bank03:49:41UTC zero-resource release. Transfer EXCLUSIVE PG now to `native_intake_collaboration` for actual9h4 Task3. No other owner may collect/query PG. Use only existing private UUID financial/legacy fixtures at that exact current head; no schema/model/migration change is granted.

Execute the two new ordinary test files through the installed Container/main-router signed TG/MAX graph and actual producers. Fix concrete new harness/fixture defects in those two owned files without replacing SQL/results or weakening behavior; record setup failures separately from runtime RED. Keep the20 accepted runtime/source tests frozen and coordinate any actual runtime defect. Existing partner_view_api/selection_view_api/campaign_summary PG files may receive only a concrete typed-proof fixture compatibility change preserving all assertions; no broad shared-fixture change. Verify the actual first actor SELECT establishes RR READ ONLY with no earlier PID/settings SELECT, actual driver PIDs and bounded independent writer completion in both orderings. No blocking-wait claim is warranted for these reader cases. Preserve actual private-source coherence, native/status/role/membership/foreign/unknown/no-country and emitted no-DML/no-lock evidence.

Run the new PG group and required existing three-family carry, then a fixed explicit union of relevant accepted9h3/source/private-view regressions sufficient for the honest exact98 whole14-runtime-file gate, including the entire central API. Measure the new executable helper too and report the original14-runtime fraction separately, so helper coverage cannot conceal a runtime failure. One fresh sysmon explicit whole-file trace, no multiple dotted sources or new omission/exclusion/floor/precision change. Do not sum overlapping groups. Finish quality, exact final source/cohort/PID evidence freeze and report, then fresh zero-resource release for independent review. Private DSN stays inside runner processes and never in output; no live providers, messages, flags, commit or deployment. Correction Task4 remains dormant source/pure; its confirmed early-intent relation gap grants no concurrent schema or PG work.

### Root coordination: confirmed early-refund intent relation gap

The Task4 owner confirmed root's concrete source concern: an immutable early `refund_intents` row retains nullable request/capture/payment/bundle/review fields; observation and physical owner retain that stable intent ID. The current deferred application guard resolves approval through that same row and requires observation.intent_id=application.intent_id, so neither filling the old row nor replacing it with a new approved intent is valid. Keep that early-to-approved path unavailable at the current head. Review the proposed additive immutable approval/binding record plus exact match link before schema implementation, preserving stable economic ownership and actual old complete-intent provenance. The Task4 checkpoint must describe records/FKs/source/version checks, legacy compatibility without fabricated approvals and deferred-guard/data-preservation behavior. Necessary trusted pure records/protocols fit the current source grant; schema/model/migration/PG changes do not. 9h4 retains sole PG at the unchanged head, and other Task4 source work continues.

### Root handoff: campaign service source fix review

Root read `task-10b2-service-fix-report.md` and the new manifest `task-10b2-service-fix-freeze.json` (SHA-256 `e7770489e5031b665c464d34ec352da89dc3e6c38d6b256d95e48b8f0b8f4e9a`). Builder261 tests and exact1018/1025=99.3170732% across the same seven whole modules pass, zero exclusions, quality12/7 clean. Only the two authorized author paths changed; corrected reproduction and unaffected frozen/historical artifacts remain preserved. Fresh independent fix review must verify both Important findings, root's exact reproduction correction, direct-decision refusal and safe fresh rejection with preserved negative approval/native/admin/receipt semantics. Repeat the exact nine-file pure gate and whole-seven-file measurement/quality with fresh data and hashes; no source/test changes or PG is granted. Source/pure acceptance remains pending that verdict. 9h4 continues as sole PG owner; Task4 correction work remains dormant source only.

The analysis canvas now reflects accepted common-proof/P01 cutover in R03/P01/R05 and the next-result paragraph. Whole-stage limits and unchanged20/30 status totals remain explicit; inline JSON/unique IDs were checked, no TypeScript/render claim. Evidence: `task-root-analysis-proof-cutover-acceptance.json`.

### Root acceptance: dormant campaign service source after fixes

Read `task-10b2-service-fix-independent-review.md`: both Important findings closed with no new Critical/Important issue; fresh261 tests, exact1018/1025=99.3170732%, zero exclusions, quality12/7 clean and67 unique preservation references intact. The root reproduction correction is independently verified as the sole AST relocation, with all original assertions intact and original bytes archived. Accept only coherent dormant Tasks2–4 SOURCE/PURE behavior. Actual SQL/source provenance/barriers/persistence/concurrent capacity, signed integration, UI, worker/outcomes/replies/reports and fullM02 remain open. No later campaign source/SQL/integration grant follows implicitly.

### Root review assignment: additive early-refund approval relation

A fresh independent read-only design worker may review the confirmed early-intent relation gap against the actual frozen schema/guard, stable proof-owner port and approved Task4/Task6 semantics. Evaluate the proposed immutable approval/binding record and explicit match link, exact source/request/review/version/case validation, genuine complete-legacy-intent compatibility without fabricated approval IDs, cumulative/application/observation/proof invariants and data-preserving downgrade behavior. Provide the minimal additive contract and concrete risks in `task-6ca1-approval-binding-design-review.md`; no new business eligibility or guessed economic facts. This grants no implementation, model/schema/migration, module import/test/engine, credential/routing/database activity or PG slot. 9h4 remains sole PG owner at the unchanged head; the Task4 owner continues its existing source boundary and early matching stays unavailable until coordinated storage support exists.

### Root handoff: 9h4 independent snapshot SQL review

Root read `task-9h4-sql-report.md`, final freeze `task-9h4-sql-freeze-sha256.json` and fresh04:03:26.514706UTC zero-resource release. Builder1365 passed/no skips in71.26s, exact1708/1736=98.3870968% original14 runtime files; helper193/195 and inclusive1901/1931=98.4464008%, zero exclusions.52 completed distinct reader/writer pairs establish nonlocking snapshot completion, not waits. All20 accepted source and two prepared test bytes are unchanged; no runtime/old-fixture correction was needed. Environment-only initial MAX-token and mypy invocation failures remain preserved. Source quality22 clean;66 unique repository paths and18 artifact hashes are frozen. No independent acceptance yet.

Transfer EXCLUSIVE PG to `native_snapshot_source_review` for a fresh bounded SQL review of that exact51-file union and15-whole-file trace, reporting the original14-runtime fraction separately. Verify current head, hashes/source, installed signed TG/MAX graph, actual first-SELECT boundary/settings/native/private coherence, all52 distinct-PID completions and no reader writes/locks. Reuse isolated UUID financial/legacy fixtures only at unchanged financial_corrections_a1; no model/schema/migration/source/frozen-test edit. A new ordinary reproduction is allowed only for a concrete finding. Private DSN stays inside runner and is never printed; no live/flag/commit/deploy work. End with fresh zero-resource release and report for root acceptance. Other agents have no PG authority; the approval-binding review remains documentation only and Task4 source stays dormant.

Fresh primary `git fetch origin` also succeeded; `main...origin/main` remains0/0 at6505af2 and the user's dirty primary files remain untouched. M02's analysis entry now records the accepted261/source-pure99.32% boundary after both fixes, preserving all20/30 status totals and explicit remaining SQL/UI/delivery work. Evidence: `task-root-analysis-campaign-service-source.json`.

### Root acceptance: early-intent approval relation design

Read `task-6ca1-approval-binding-design-review.md`: the additive immutable approval plus exact match link is sufficient with the pinned contract; no new product decision is needed. Prefer a new immutable match-link table so historical schema builders stay unchanged. Preserve effective review versus current event-version distinctions, exact actual command/event/source attribution, nullable early case values, original same-intent proof owner and equivalently strict complete-legacy branch without backfill or malformed-binding fallback. Protect awaiting-assessment matches before an application exists. Task6 must validate the pre-issue correction seal separately from the capture hash and the genuine expected newly issued client grounds; it cannot globally bless a changed hash. New metadata hooks must install the final companion guard after all old hooks. Populated new-history downgrade refuses before DDL/guard restoration. This accepts the compatibility design only: no schema/model/migration or PG grant; current early matching stays unavailable and Task4 source proceeds under its existing boundary.

### Root release: new campaign moderation HTTP source only

After accepted dormant261/source-pure behavior, release only NEW `miniapp/campaign_moderation_api.py` and NEW `tests/unit/test_campaign_moderation_api.py` to the campaign owner for the new moderation-router portion of Task5. Use the accepted unchanged campaign principal/commands/services and strict typed existing-only proof. Implement the seven planned submit/cancel/queue/review/approve/reject/settle-expiry endpoints with endpoint-selected decisions, strict bodies/no query or authority/source/contact/recipient overrides, safe explicit error maps and a full constant no-store validation/resolver/context/service/serialization boundary. Known domain codes map to canonical status regardless arbitrary thrown HTTP status; unexpected values are constant503. Preserve exact original operation intent/replay/fresh state and native/action authority before private admission; pure HTTP regressions must retain remap-over-cap and accepted replay after audience growth with declared synthetic source facts. Missing uninstalled services/transactions are unavailable, never successful stubs.

This router remains unmounted. Existing campaign draft/review API/service/ports/repository, accepted seven service modules/principal/templates/commands, root API/factories/types, shared native error wrapper, configuration, metadata/schema/migrations and other files remain frozen. No actor-UUID-only partial conversion of the old draft path is granted; complete native/source integration is a later coordinated step. Do not add dispatcher/factory placeholders or claim actual root/SQL integration. Tests may use actual dormant services with explicit synthetic repository/TM boundaries and real synthetic signed init data where useful, but cannot establish SQL provenance/locks/atomicity. Run meaningful source RED/GREEN and an honest explicit whole-module sysmon gate including the complete new router and relevant accepted principal/services at unchanged exact98, plus scoped quality and preservation. Freeze/report before fresh review. No PG import/collection/engine/credential/routing/query, UI/worker/send/flag/commit/deploy. The independent9h4 reviewer alone owns PG.

### Root acceptance: private read snapshots 9h4

Read `task-9h4-sql-independent-review.md` and fresh04:10:15.490036UTC zero-resource release. No Critical/Important issue; independent1365 passed in71.51s, no skips. Exact whole14-runtime1708/1736=98.3870968%, helper193/195 and inclusive1901/1931=98.4464008%, zero exclusions.52 completed distinct reader/writer cases verify same-snapshot native/private facts, first actor SELECT, RR READ ONLY and no reader DML/locks; no blocking-wait claim. All20 accepted source/two prepared files stayed unchanged; quality22 and66 repository/18 evidence/config references matched. All six runner/children and104 observed backends ended; zero other sessions/private schemas/owned processes, verifier disposed. Accept bounded9h4 and its formerly failed source-only98 gate as now covered by actual SQL/broad evidence. The bounded plan is complete; broader campaign/social/legacy callers, devices, whole-tree gate and sprint remain open. PG is free; no new schema/SQL owner is granted implicitly.

### Root checkpoint: current analysis and archive recheck

The canvas now records accepted9h4 in S01/O01 and its next-result paragraph, with unchanged20-task totals2/15/3 and30-criterion totals14/13/3. Inline JSON/unique IDs/counts were checked, no TypeScript/render verification claimed. Evidence: `task-root-analysis-9h4-acceptance.json`. A fresh direct ZIP-byte comparison again confirms all24 regular archive files/187653bytes equal existing feature assets; archive SHA remains988715875d60bf678916c7e3a161e539d1cef6fccab9daee53dfb753b6818a6b. No asset extraction/rewrite was needed. Evidence: `task-u01-current-archive-recheck.json`. An initial report-shape inspection assumed a dictionary where the existing audit is a list; the read-only direct comparison corrected that inspection error and passed.

Current active source owners remain correction Task4 and the new unmounted campaign moderation router. Both are source/pure only. The early-refund relation design is reviewed, but no companion schema/model/migration or new PG owner is released. Await Task4 source checkpoint before coordinating its concrete next storage/SQL phase. Accepted9h4 source/root API stays frozen; old campaign draft integration and global native follow-ups remain explicit. The full-document goal, fresh whole-tree makefix, full30/25/5 and external legal/provider/paid-pilot facts are not complete. No commit, push, flag activation, live send or deployment occurred.

### Root handoff: correction Task4 source review

Root read `task-6ca1-task4-source-report.md`: builder250 pure tests, scoped quality clean and31 historical paths preserved; whole-three-file557/804=69.278607%, zero exclusions, correctly FAILED98 because the actual SQL repository remained unimported/unexecuted. No source acceptance or PG grant follows. A fresh independent source/pure reviewer may verify the six-file freeze, repeat the same explicit cohort/whole-file failed-gate measurement and quality, and review exact own/admin/native/barrier/replay/request/review/observation/proof/match/read semantics. Root identified a concrete ordering concern to assess: service `_authority` calls `lock_scope` before current actor/native validation, while the actual repository performs private `load_scope` checks inside that method before returning. A stale native actor plus changed source may therefore receive source retry before native refusal. Prove or dismiss this with ordinary source evidence; a new pure reproduction is permitted only for a concrete finding. No source/frozen-test/schema/model/migration/PG/import/engine/credential/database change is granted. Early matching remains unavailable and the reviewed approval relation is a separate later storage phase.

### Root preflight: remaining D01 and social native plan

Read `task-d01-filter-source-audit.md`: current campaign backend already consumes additional-platform presence/work format through the accepted shared predicate, so the prior blanket absence claim needs correction. Campaign segment UI, persisted order/offer targeting and paid-interest revalidation remain missing; numeric metrics stay unavailable. Social editor still receives UUID-only authority with registration/country fallback before its transaction, so accepted9h4 does not close this separate capability. The audit changed no source/tests and ran no DB/tests. Release a focused PLAN ONLY for social native9h5 to that source auditor: define typed existing-only HTTP proof plus current native/status/owner/canonical-Instagram authority inside the actual coherent read/write transaction, preserving supplemental unverified data and sequential editor semantics. No new product rules or order-platform schema are included. No implementation/engine/tests/PG/schema/API/factory/UI changes are granted; root separately coordinates exact source and single API injection after plan review.


### Root handoff: new moderation HTTP source independent review

Read `task-10b2-http-source-report.md` and final freeze `task-10b2-http-source-freeze.json` (manifest SHA-256 `3eedf5331b008a490ea29c0a6485261cb3d8cc73076f83bb2078b43b635e1be2`). The two new unmounted paths report 473 pure/HTTP tests, exact 1438/1449=99.2408558% over eleven whole runtime modules, zero exclusions, new-router115/115, scoped quality2/11 and38 source/test plus71 historical artifact preservation. This is builder evidence only. Release a fresh independent source/pure review of the strict seven signed endpoints, typed existing-only authority, canonical finite public errors/full no-store boundary, serialization inside the supplied transaction and actual dormant-service replay/negative-authority behavior. Repeat the exact manifest cohort/whole-module gate and quality, inspect all frozen preservation references. A new ordinary pure reproduction is permitted only for a concrete finding; frozen files remain unchanged. No PG imports/collection/engine/credentials/query, root/factory integration, schema, UI/send/flags/commit/deploy is granted. Full Task5, SQL and M02 stay open.

### Root finding and release: correction Task4 authority ordering fix

Read `task-6ca1-task4-source-independent-review.md`: one Important defect is confirmed. The full repository `lock_scope` loads private scope and initializes wallets before current native/admin/own authority. Six ordinary pure required-denial reproductions fail and the authorized-source-refresh control passes. The original250 cases pass, but the honest whole-three-file557/804=69.278607% source gate remains FAILED98, not waived. All six frozen and31 historical files are preserved. This checkpoint is not accepted.

Release a narrow source/pure fix to the original Task4 owner in its existing ports/service/repository/helper/test paths only. Establish the complete sorted prospective User barrier first, then current native/status and action-specific own/admin authority, then wallet initialization and downstream private/economic locks/source validation. Do not take an actor-only preliminary lock, add late User locks, remove/relabel source checks, weaken source retries or defer applicable operation/case authority until after private diagnostics. A narrow explicit User-preparation interface is allowed where needed; preserve existing complete-set/source retry semantics and trusted routing facts without returning private contents early. The new independent reproduction is permanent and must remain unchanged; add further owned tests for actual ordering/authorized source retries as needed. Preserve all unrelated accepted/historical bytes and record intentional supersession of owned Task4 hashes. No schema/model/migration, actual PG import/collection/engine/credentials/query, factory/root ingress, compensation or early-binding implementation is granted. Retain the failed whole-file SQL-dependent coverage honestly; run fresh pure reproductions/cohort and scoped quality, freeze/report for fresh independent review before any SQL grant.

### Root analysis checkpoint: D01 source correction and archive scope

The canvas D01 entry now reflects the verified existing campaign platform/work-format predicate, remaining campaign segment UI and order/offer/paid-selection targeting, and the separate social editor native-authority gap. All41 audit source hashes were rechecked unchanged; evidence `task-root-analysis-d01-source-correction.json`. No status totals changed. U01 already accounts for the archive's24 identical regular files and retains real-device/full-journey gaps. No new asset application was requested or performed.


Root refreshed origin again during the current archive follow-up: primary main and origin/main both remain6505af277fd01ab83fc7f2ba5ba07eba81bd2396, with the same untouched user dirt. The U01 canvas wording now explicitly separates the24 matching archived files from runtime asset use and reference Markdown component descriptions; status totals stay unchanged. Evidence `task-root-analysis-u01-archive-scope.json`; inline JSON/IDs/counts checked, no render/TypeScript claim.


### Root acceptance: new unmounted campaign moderation HTTP source

Read the full `task-10b2-http-source-independent-review.md`. No Critical/Important finding; fresh473 tests in1.84s, exact1438/1449=99.2408557626% across eleven whole runtime modules, zero exclusions; new router115/115. AST/compile, Ruff/format2 and mypy11 pass;126 unique preservation references match, including38 frozen source/test and71 historical artifacts. Static search confirms no production import/mount beyond the new module. Accept this bounded SOURCE/PURE HTTP layer only. Actual root/factory graph, SQL persistence/current-native barriers/transaction atomicity/concurrent capacity, fullTask5/Task6, UI, delivery and M02 remain open; no PG or later implementation grant follows implicitly.


### Root preparation: campaign storage source feasibility only

After bounded HTTP acceptance, release a READ-ONLY source feasibility inventory for the already accepted Task6 contract to the campaign owner. Map actual frozen repository Protocol methods/records to existing foundation/draft/source tables and the planned additive storage; identify exact narrow draft/native compatibility and root factory/injection edits, full prospective-User discovery, sorted barriers and bound read/write context implementation requirements. Check schema/FK/journal/envelope/projection/downgrade compatibility from files only and report any concrete gap or collision. Produce only `task-10b2-storage-source-preflight.md` and a hash/explicit future-file inventory under the report directory. Do not edit the accepted plan, source, tests or add schema/models/migration files. No imports/collection/tests, credential/routing/engine/database/query or PG ownership is granted; no guessed migration parent. Current correction source fix and social-plan writer retain disjoint boundaries. Root assigns shared integration and the exclusive actual schema/PG stage separately after reviewing this inventory.


### Root handoff: social native9h5 independent plan review

Read complete `2026-10-24-umc-social-native-9h5.md` and `task-9h5-plan-report.md`; frozen plan SHA-25605d38e463d9bf52ae8ea14a8daf27127ec107ccc5abc37c7526fca4cdf73194a. The explicit authenticated aggregate facade/coherent facts and preserved compatibility fit the bounded goal. Fresh independent READ-ONLY design review must assess actual source/type/session/barrier/first-SELECT/freshness/current status/profile/own-removal/no-store/error behavior, unchanged trusted methods and the exact root two-edit boundary, with no new business rules. Root found a concrete collection concern: proposed service and PostgreSQL test basenames are both `test_social_editor_native.py`, while neither directory has __init__.py and no importlib mode is configured; specify a unique PG basename before execution. Also assess the frozen shared route base's exception stringification against the intended full constant no-store failure boundary, without editing that frozen base. Produce `task-9h5-plan-independent-review.md` with concrete findings/minimal amendments and source evidence; no plan/source/test edits, imports/collection/test/engine/credential/routing/database/PG work. No implementation or PG grant follows until root reads that verdict and any plan correction.


### Root handoff: correction authority-order fix independent review

Read `task-6ca1-task4-order-fix-report.md` and manifest SHA-2566717aab2d67ed17bdc7f607801683040f894bdc318209690f2fbc1f6ae20b88e. Builder268 pure cases pass, scoped quality clean; complete runtime588/855=68.7719298%, SQL0/267, FAILED98, with six newly enumerated normal configured Protocol placeholder exclusions and no policy change. The permanent repro and31 unrelated historical paths remain preserved. Fresh independent source review must verify complete User preparation → current actor/native/status → action-specific current owner/admin → downstream wallet/source stages, the narrow scalar routing authority and changed-current-advertiser denial, all original repros/control, compatible trusted lock_scope and no late/repeated service User locks. Repeat the manifest seven-file cohort/whole-three-file failed measurement/quality and hashes. No frozen file edit or PG import/collection/engine/credential/query is granted; a new ordinary pure repro is allowed only for a concrete finding. Source review cannot accept the missing SQL gate.

Coordination: the first social-plan-review dispatch was rejected because all four slots were occupied, including the campaign preflight child; no review ran and no acceptance followed. That read-only child has now completed. Use the available fresh campaign HTTP reviewer for the social9h5 plan review and the original correction finding reviewer for the correction fix review. Both remain read-only within their respective source/plan scopes; the campaign inventory continues sequentially. PG stays free with no owner.


### Root release: correction Task4 complete case/request binding fix

Read full `task-6ca1-task4-order-fix-independent-review.md`: original authority ordering is closed in source/pure268, but a new Important incomplete immutable binding remains. Request-first read authority discards conflicting non-null case.client_id and case.order_id. New permanent matrix has4 failed/3 passing NULL-early controls; SHA-25630bf4482feaa9695ec8c858366c8447770f146835976b23097136cf9077841e0 at `tests/application/services/test_correction_owner_binding_review_repro.py`. Current checkpoint is not accepted; whole runtime98 gate remains FAILED pending SQL.

Release a narrow SOURCE/PURE fix in the same six owned Task4 paths. Retain separate narrow scalar case/request/current-order bindings rather than replacing one with request-first values. After complete User preparation and current native/status plus applicable own/admin/action authority, validate present case client/order agreement with the genuine request/current order before wallet/private-scope/receipt access. Preserve genuinely NULL early client/order, current-advertiser denial, authorized source retries and all previous ordering properties. Do not expose a consistency oracle before foreign/native/admin denial, mutate immutable history, add schema/migration, late User or permissive fallback. Both independent reproduction files are permanent and byte-frozen. Run at least the prior268 plus new7 reproduction cases and meaningful owned refusal-order controls, honest whole-three-module measurement/quality, then freeze/report under `task-6ca1-task4-binding-fix-*` for fresh review. All31 unrelated historical paths, accepted binding design and earlier reports remain unchanged. No SQL/PG/import/engine/credential/query, factory/ingress/compensation or early-binding storage grant.

### Root release: social9h5 plan amendments only

Read full `task-9h5-plan-independent-review.md`: two Important planning corrections; no source execution acceptance. Original plan author may amend only the existing9h5 plan and write a new amendment report/hash, preserving original review artifacts. Use unique `tests/postgres_financial/test_social_editor_native_pg.py` throughout. Replace unsafe inherited error execution with a social-only explicit safe raw APIRoute handler, keeping the frozen native wrapper unchanged; classify exact plain-string known detail/single argument without str/repr/logging, include unsafe conversion regressions and canonical no-store errors. Pin same storage/editor object, actual configured bind/root/no-nested session metadata validation before SQL, no autoflush, earlier-transaction stale-cache preload, full detached saved/next validation before facade commit and the honest later HTTP-serialization limitation. Retain the campaign absent-social-row dependency on the new User-fenced reachable HTTP writers, both accepted compatibility rules, exact two root edits and whole-seven-module98 scope. No new business rule/framework or product source/test/helper edit, import/collection/test/engine/credential/DB/PG action. Return amended plan/hash for fresh read-only re-review before any implementation.


### Root deferred native-error follow-up

The9h5 plan review identified a concrete control-flow limitation in the frozen shared `_NativeCallerRoute`: exceptions raised by arbitrary exception stringification inside its own except clause can escape the constant no-store tail. The social plan avoids that execution with its local safe handler; this does not repair or reaccept other shared-wrapper callers. Retain a separate later bounded shared-wrapper regression/fix/review after current frozen source coordination, with exact plain-string classification and existing code/status compatibility. No shared-wrapper edit is granted by the social plan or campaign inventory; their accepted hashes remain frozen. This is source-evidence follow-up, not a claimed executed production incident or new external blocker.


### Goal continuation checkpoint and correction binding-fix handoff

The previous goal turn made progress: independently accepted the unmounted moderation HTTP source, corrected U01/D01/M02 analysis, and produced two concrete correction findings/permanent reproductions that changed the next implementation action. Full sprint completion remains unproven; no blocked condition prevents internal work.

Read full `task-6ca1-task4-binding-fix-report.md` and manifest SHA-2568cc55b35176008c15d842e27cad873280b656ea511193538eea078821f4c35ac. Builder284 pure cases and scoped quality pass; full runtime601/868=69.2396313%, SQL0/267, FAILED98, same six normal configured placeholder/blank exclusions. Distinct narrow case/request/current-order scalar bindings now survive routing and are checked after applicable authority and before downstream scope. Both permanent repro files,31 unrelated historical paths and accepted design match; prior evidence is preserved. Release fresh independent source/pure fix review of complete binding, NULL-early compatibility, all native/status/own/admin/refusal precedence and unchanged source retry/complete User order. Repeat exact eight-file284 cohort, whole-three measurement/quality and preservation before/after. No frozen file edits; a new ordinary pure repro is allowed only for a concrete finding. No PG/import/collection/engine/credential/query/schema/root/factory/compensation or early-binding authority.

### Root reproduction-only scope: shared native error conversion

Root may create NEW `tests/unit/test_native_caller_error_safety.py` and run only its pure in-process ASGI regressions to establish the deferred unsafe exception-conversion defect. Use actual existing shared route classes with explicitly synthetic failing endpoints, no replacement handler and no engine/database. Capture meaningful public503/no-store/no-conversion failures plus known-code compatibility controls; record exact outcomes and preserve shared source hash. This grants no edit to frozen `native_caller_errors.py` or other source/test, no PG and no broad gate. A later bounded shared fix remains separately coordinated.


### Root handoff: amended social9h5 plan re-review

Read `task-9h5-plan-amendment-report.md`, amendment evidence and changed plan sections. Amended SHA-2563581047a7b545b0e8884909c4feed7ecdffba2f788e433262cdf2e828dc125ce. Both Important corrections and narrow session/result/dependency pins are now expressed;20 protected source/artifact hashes match. No source/SQL acceptance follows documentation checks. Release fresh independent READ-ONLY re-review of the amended plan, exact two findings and compatibility/scope consistency, preserving all other source. Write `task-9h5-plan-amendment-independent-review.md` with current hash/verdict; no source/plan edits, imports/tests/checkers/engine/credential/routing/database activity. Root separately adds one NEW disjoint pure shared-error regression file while leaving the shared wrapper unchanged; that addition is not a change to the18 reviewed source bytes.


### Root acceptance and release: correction Task4 current-head actual SQL

Read full `task-6ca1-task4-binding-fix-independent-review.md`: both Important source findings closed, no new Critical/Important; fresh284 in0.71s, quality and6 owned/31 historical/2 permanent repro/design/policy references match. Exact runtime601/868=69.2396313% still FAILED98 because SQL0/267; that gate is not waived or accepted. Source is ready to acquire missing actual SQL evidence.

Root re-read the independent9h4 resource release04:10:15.490036UTC: all runners/backends ended, zero other sessions/private financial/legacy schemas/owned process-group members, engine disposed, explicitly released. No subsequent PG owner was granted. Current static head preflight is sole financial_corrections_a1, parent campaign_drafts_v1; its migration hash remains2e94cbade3fe0ba00e2d7d657f5940e4800ce7b1b1801b053622008e26a46f00. Transfer EXCLUSIVE PG to corrections_a1_contracts for Task4 PhaseA at this unchanged head only. First verify a fresh resource baseline; do not clean another owner's resources.

Release NEW `tests/postgres_financial/test_correction_commands_pg.py` and NEW `tests/helpers/correction_runtime_pg.py` for actual service→SQL repository→common proof authority in the existing Container caller transaction, using actual intake/quote/invoice/capture and declared synthetic bank observations. Existing helpers/corrections.py and all accepted schema/model/migration/P01/proof files stay frozen. Prove genuine own request→actual active-admin review→retained observation/common claim→fresh exact match awaiting_assessment only; accepted replay/result versus fresh state/read privacy; refusal/source/bundle/version/current native/admin/own checks; rollback/retained recognized observation behavior. Preserve the early stable-intent path as explicitly unavailable until its separately reviewed companion exists. No compensation/application/forward guard, monetary cancellation or signed correction ingress is installed in PhaseA.

Cover actual TG/MAX typed-native/current-role/current-owner orderings with distinct driver PIDs and bounded observer-backed waits, complete sorted User barriers before downstream economic scope, current authority before simultaneous source/binding failure, no late User and genuine current-source retry. Include complete case/request non-null consistency and NULL early controls against actual retained facts, not substituted SQL results. If normal producers cannot create a corruption, identify raw private SQL fixture corruption as such rather than pretending it is an admitted producer. Source/harness corrections inside the same owned Task4 files are allowed only for concrete actual failures consistent with the accepted contracts, preserving repro assertions and recording RED/provenance; report the change immediately and freeze it for later independent review. No immutable-history weakening or schema workaround is permitted.

Run focused new SQL then a fixed explicit union of the284 pure cohort, required existing correction storage/source/migration/residual and common-proof carry sufficient for the exact whole-three-runtime98 gate. Use one sysmon package/explicit whole-file trace, no multiple dotted sources/new omit/exclusion/floor change; report helper fractions separately, no overlapping-count sums or default rounding. Scoped quality for every changed path, final freeze/report and fresh zero-resource release are required before independent SQL review. Once genuine complete captured approval/observation/match producer bytes actually work, coordinate a portable pre-approval-binding writer fixture BEFORE any later companion edit; do not manufacture old approval IDs or use the old request-as-review synthetic shortcut. Creating that portable fixture will be separately pinned from the proven bytes. New companion schema/model/migration/parent remain UNASSIGNED and unreleased. DSN stays only inside runner processes, never output; only private UUID financial/legacy schemas, no live/provider/send/flag/commit/deploy. All other agents have no PG access.

### Root acceptance and release: social9h5 owned source/pure

Read full amended-plan independent review: both Important plan corrections closed, no new finding; amended plan3581047a7b545b0e8884909c4feed7ecdffba2f788e433262cdf2e828dc125ce and20 protected references verified. Accept the bounded design and release only owned Tasks1–3 SOURCE/PURE: modify social ports/service/SQL social repository/social API; NEW social_errors.py; NEW tests/helpers/social_editor.py, service-native unit and social-editor API unit files. Narrow fixture compatibility in existing test_miniapp_social_accounts.py may preserve all old assertions with explicit typed/synthetic editor capability. Root central api.py/service_factory.py, new wiring tests, existing Container test and every other source remain frozen until the owned source checkpoint. No runtime fallback or new registry/type/model/schema/config/UI is released.

Implement the exact required-principal aggregate facade, same storage/editor object, coherent read/save next-platform, current native/status/owner/canonical-profile semantics and local safe raw error handler in the reviewed plan. SQL source is dormant preparation: ordinary negative guard tests may use unbound AsyncSession metadata and explicit synthetic boundaries/compiled statements, but no engine, real connection/query or claimed SQL/lock proof. Run meaningful RED/GREEN on the new service/API plus unchanged trusted-service and narrowly compatible social API tests, whole-five-runtime-file sysmon measurement with actual SQL misses retained, separate helper measurement and scoped quality. No SQLite Container engine or PG test import/collection/credentials/routing/engine/query is granted in this source phase. Freeze/report before root's exact two integration edits, independent review and later exclusive SQL phase. Current correction owner alone owns PG. Keep shared native wrapper, all accepted campaign/9h4 source and profile/verification writers unchanged. Current public social resolver may be temporarily incompatible until root's coordinated injection; do not add a UUID fallback to conceal that integration gap.


### Root acceptance: campaign storage source inventory

Read full `task-10b2-storage-source-preflight.md` (SHA-2563f9854bc9a07a6c700a63630a39e4953c91293cfece354738a9c5d992af4bf1a) and its concrete six prerequisites. The combined actual repository Protocol and private context provenance, canonical primitive SQL field conversion,9h5 absent-social-row fence, old typed-native/lifecycle/receipt compatibility, eleven-table compound source/evidence relations and exact five root integration files are feasible within the accepted contract. The existing full-User/profile StrEnum boundary is a source-level compatibility finding, not yet an executed SQL regression.40 accepted/64 inspected/95 historical/3 references/120 migrations are overlapping groups and were preserved at this read-only checkpoint. No schema or new migration parent is assigned. Correction PhaseA retains exclusive PG;9h5 source proceeds. The inventory is accepted as preparation, not persistence/source/SQL/M02 readiness.

### Root release: shared native error safety source/pure fix

Campaign inventory and9h5 plan reviews stopped with the shared wrapper unchanged. Root's actual ASGI reproduction confirms30 failing unsafe-domain cases/6 compatibility controls, then ten additive unsafe HTTP detail cases give40 failed/6 controls. Raising conversion yields(500,None) rather than(503,no-store); spoofed conversion changes an unknown private argument into known403. Initial36-case source is archived at `task-root-native-error-safety-initial-test.py.source` so original SHA35f0a0737c591217c87ad2a67c37394e6f01de30ebc3ecb9df214a072d3c6b75 remains inspectable. Earlier RED logs are preserved.

Root now owns a narrow SOURCE/PURE fix only in `miniapp/native_caller_errors.py` and the new permanent safety test. Intentionally supersede this one accepted shared-wrapper hash72b160e8791684c4863b7fa17cea0a36bdd94452511d203cd6f607c8b1461bf9; all other accepted runtime/tests stay unchanged. Never stringify exceptions or compare/hash non-plain-string HTTP/domain values for classification. Only exact one plain-string domain argument or exact plain-string HTTP detail can enter the existing finite map; unknown shapes use the existing caller prefix unavailable503. Preserve every public code/status, collaboration scoped404 exception, canonical wrong-status mapping, safe headers and full no-store boundary. No new global helper/framework, API/factory/proof/schema/source change is included.

Run the unchanged failing safety matrix plus fixed pure native caller/private snapshot API compatibility cohort, exact whole-wrapper sysmon98 gate and scoped quality; freeze/report then obtain fresh independent review. Root explicitly notified9h5 source owner that this one root-owned preservation reference will change; its direct social handler/source scope remains unchanged. Current correction owner alone owns PG; this fix constructs no engine/imports no PG tests and has no credential/routing/query/provider/send/flag/commit/deploy action. It does not reaccept wider9h3/9h4 SQL or whole-tree readiness merely from a pure wrapper gate.


### Root handoff: shared native error safety independent review

Root-owned fix is frozen at `task-root-native-error-safety-freeze.json`, manifest SHA-256f0f0812e908d3ade8582450ac748beed5b34e0cffccaf357f6edfb20e59fe9fe. Actual coherent three-file260 in0.88s, whole wrapper62/62=100%, zero exclusions, Ruff/format2 and mypy1 pass. All34 latest accepted9h3/9h4/policy references match. The initial hash check used one stale9h3 native_caller_api test reference; current bytes match the later independently accepted9h4 SQL freeze and the manifest records that correction, without modifying that test. The only intentional runtime supersession is wrapper72b160...→68798c1898c3892684ecac3b72594b76aac0587bb0958719661026661005fd18. Original source bytes are recovered by exactly reversing the known edits and hash-verified to the recorded old bytes, with that provenance explicitly labelled; initial36-case test and all RED logs remain archived.

Release fresh independent SOURCE/PURE review of only this runtime and new safety test, unchanged code/status maps and collaboration404 compatibility, exact plain-string domain/HTTP classification/no conversions/full no-store and preserved actual signed pure API behavior. Repeat exact260/whole-one-file sysmon98/quality/preservation with fresh data. No source/frozen-test edits; a new ordinary pure repro is allowed only for a concrete issue. No PG imports/engines/credential/query/DB, source/API/factory/schema broadening or wider9h SQL acceptance. Write `task-root-native-error-safety-independent-review.md`, then stop. Current correction owner alone owns PG and9h5 author continues disjoint source; root API/factory stay frozen.


### Root finding/release: shared error HTTP-status guard

Read full `task-root-native-error-safety-independent-review.md` and the complete new ordinary repro. Domain/detail conversion fixes are accepted as corrected behavior, but an Important residual remains: a known plain-string code still hashes an unvalidated thrown status in the override tuple.10 actual RED cases yield500/no-store absent/hash invoked, while the exact260/whole62/62/quality/preservation gate passes separately. The source checkpoint remains unaccepted.

Release only a narrow root-owned wrapper fix: initialize canonical status from the trusted known code; use the existing pair override only for an exact plain int status. No hashing/conversion/comparison of other status shapes; preserve ordinary collaboration404. The independent reproduction SHA3c1cab561975c302be1515304f7b7a03cb6acd8ce9b6c69087da8992aa9d57fa and original safety test remain byte-frozen. Directly archive intermediate source68798... before editing. Repeat exact original260 plus10 repro as one270-case source/pure union, whole-wrapper98 gate/quality/preservation, new freeze/report and fresh independent review. No other source/test or current PG ownership changes;9h5 direct social wrapper stays independent and its root-owned preservation supersession will be updated.


### Root handoff: shared native status fix re-review

Read the full independent status finding and directly archived intermediate source before the narrow guard. New freeze `task-root-native-error-status-fix-freeze.json` SHA-256e618dda4944465540a097ad634846b489c3d6eee01923f50a3432a0d8dbb163b; source72435f4bbd60c7b3e6c87f66868f251bb87b434ed9a7b849f5b6c58aacce6c84 intentionally supersedes interim68798.... Builder270 in0.87s, whole65/65=100%, zero exclusions, quality3/1 pass. Both permanent tests,34 latest accepted references and32 historical artifacts are preserved. Release fresh independent SOURCE/PURE re-review of the exact ordinary-int override guard and all previous classification/status/no-store compatibility, exact four-file270/whole-wrapper gate/quality/hashes. No frozen file edit; no PG/engine/query/DB/root integration/broad acceptance. Write `task-root-native-error-status-fix-independent-review.md` then stop. Other two source/SQL owners retain their boundaries.


### Root acceptance: shared native constant error boundary

Read full `task-root-native-error-status-fix-independent-review.md`: Important status finding closed, no new Critical/Important. Fresh270 in0.87s, whole65/65=100%, zero exclusions, compile/Ruff/format3/mypy1 and72 preservation references pass. Accept the bounded SOURCE/PURE shared-wrapper fix at72435f4bbd60c7b3e6c87f66868f251bb87b434ed9a7b849f5b6c58aacce6c84. Both permanent reproductions remain unchanged; earlier recovered and directly copied archive provenances stay distinct. This resolves the deferred shared-error follow-up; it does not stand in for whole9h SQL, whole-tree makefix, device or sprint acceptance.

### Root handoff: correction PhaseA independent actual SQL review

Read full `task-6ca1-task4-current-head-sql-report.md`, both complete new PG/helper source files, final freeze SHA-256b0234714356294f50d46b84ba38677d9950059aa268e16d97a609991fca791c0 and fresh05:12:04.015215UTC zero-resource release. Builder425 in123.45s/no skips/warnings, original runtime867/868=99.8847926%, helper200/204=98.0392157%,60 completed observer-backed distinct-PID cases/120 final backends. All12 runners/336 recorded backends ended, zero sessions/private financial/legacy schemas/owned process groups, engine disposed. Current head and all four preservation groups rechecked by AST/hash only in `task-6ca1-task4-root-sql-handoff-preflight.json`; no root DB activity.

Transfer EXCLUSIVE PG to the fresh correction source reviewer for this exact13-file425 cohort, whole-three-runtime and separate helper sysmon measurements/quality/preservation, installed genuine request/review/observation/awaiting-assessment match provenance, replay/read/privacy/source/version/claim/rollback and all60 actual blocking orderings. Reuse existing isolated UUID fixtures at unchanged financial_corrections_a1 only. No schema/models/migrations/runtime/frozen-test edit; ordinary new repro only for a concrete finding. Check actual instrumentation and caller-Tx limits: source-retry races catch the refusal inside their test transaction, so they prove denial/no late User rather than an automatic caller rollback that was not observed. Expected-refusal retention and unexpected outer rollback have separate actual cases.

The case-binding helper explicitly injects corruption by temporarily disabling only the private immutable-case trigger, restoring it before commit and restoring original fields in finally. Root permits that narrowly labelled PRIVATE negative fault injection as test evidence, not an admitted writer, production history mutation or schema workaround; verify restoration/limits and preserve normal immutable-guard carry. No production schema/source guard is weakened. DSN stays inside runner, never output. End with fresh zero-resource release and independent report before root accepts SQL. Other workers have no PG access. Root may copy proven producer source bytes into nonexecuting portable fixtures while review runs; that changes no frozen source or selected test.

### Root handoff: social9h5 owned source independent review

Read final source report and manifest SHA-25636dc96af8e452e3ee4d40311595ba499c302642e28fd448f76d3ed7e9dbed9bf. Builder108 no-engine pure/module-API cases pass; whole-five329/388=84.7938144% FAILED98, helper103/104 separately; quality and disclosed old-helper mypy limitations remain honest. Actual root API/factory are still frozen/unintegrated. Release fresh independent SOURCE/PURE review of all9 owned paths, exact108/whole-five failed gate/helper/quality/current preservation and original API assertions, without modifying source/tests. Inspect current typed/principal/current owner/status/profile/source/session/first-SELECT/write/freshness/no-store/projection semantics against the accepted plan, keeping existing legacy compatibility. Root noticed HTTP context checks typed proof but not explicit principal.platform==body.platform; establish whether this violates the existing gateway contract with a concrete pure discriminator, rather than asserting an externally reachable exploit. A new ordinary pure repro is permitted for a concrete finding only. No engine, SQLite Container, PG imports/collection/credentials/routing/query, root API/factory or schema edit. Shared wrapper is separately root-accepted at72435..., intentionally superseding historical/interim references; social handler is direct and independent. Report then stop before root integration/SQL grants.


### Root portable pin: genuine pre-approval-binding writer source

PhaseA builder425 and the genuine request/review/observation/awaiting-assessment writer are verified, with independent SQL review currently running at the same frozen head/source. Root may copy the three exact frozen producer files (ports/service/repository) into NEW nonexecuting `tests/fixtures/corrections/pre_approval_binding/*.py.source` plus manifest. Compare direct-copy hashes and record actual head/migration, builder report/freeze/initial two-case witness and canonical dependency hashes. This archives real proven old complete-intent producer bytes before any companion edit; it does not fabricate command/approval IDs, persist financial facts, install a loader, run archived code or accept pending SQL review. The later compatibility loader must execute these exact bytes with local import substitution, never silently use the future current writer or the old request-as-review shortcut. No existing source/test/schema/metadata file changes, no PG grant to root and no companion head assignment. The fresh reviewer retains exclusive PG; nonexecuting new fixture assets do not affect the explicit13-file cohort.


### Root acceptance: bounded correction PhaseA SQL and latest analysis steering

Read full `task-6ca1-task4-current-head-sql-independent-review.md`: fresh exact425/124.38s, runtime867/868=99.8847926267%, helper200/204=98.0392156863%, unchanged98 floor,60 actual observer-backed distinct-PID blocking cases, no Critical/Important. Accept only genuine captured-first own request → active-admin review → retained observation/common proof claim → fresh awaiting_assessment match. Extra8 restoration audits overlap425; actual original client/order and enabled private trigger were verified after every fault-injection context. Writer-first expected refusals caught inside the caller TM do not prove automatic caller rollback. Separate observed expected-retention/unexpected-outer-rollback cases retain their stated limits. Source/head/preservation unchanged; fresh PG release05:25:36.583077UTC has no remaining sessions/private schemas/runner groups and disposed engine. No next PG owner, companion migration/parent or implementation is granted. Early approval/link binding, compensation, monetary guards, signed ingress and30/25/5 remain open.

Read full `task-9h5-source-independent-review.md`: Important proof/request-host binding gap remains, six ordinary RED cases/zero engines. Exact108 is green but whole-five329/388=84.79381443299% FAILED98. No source acceptance or integration/SQL grant. Default resolver constructs the correct requested host; externally reachable exploitation is not established. Preserve the new repro and frozen source.

Latest user answer is “Проверить и учесть в анализе” for the supplied design ZIP. Fresh fetch main=origin/main6505af2; independent and root byte checks confirm main0/24, feature24/24,187653 bytes, archive988715875d60bf678916c7e3a161e539d1cef6fccab9daee53dfb753b6818a6b. Current work is analysis only: provide managed `UMC-sprint-main.canvas.tsx` with20 main tasks (12 partial/8 without the new scenario), explicitly distinguish feature analysis, correct the historical feature-audit button incorrectly labelled main, disclose latest bounded feature reviews without status promotion. Existing archive/assets/runtime remain unchanged; no implementation, credential/DB/flag/commit/deploy is granted by this steering. The full active goal is not completed by this analytical delivery.


### Root resumed full goal: 9h5 host fix and integration preparation

Previous goal turn is progress: archive bytes/current main were freshly verified, authoritative analysis corrected and bounded correction PhaseA SQL independently accepted. Full goal remains active. Current explicit continuation resumes implementation after analytical steering. Release only the concrete6-case wrong-host social HTTP fix to the original source owner; preserve the repro/source boundary and repeat114 no-engine/whole-five honest failed98 checkpoint before independent review. Root adds NEW actual-main wiring tests first;14 behavioral RED cases/zeroengine prove current UUID callback cannot satisfy positive/current-denial/unknown-existing-only contracts. Root API/factory and old Container test remain byte-frozen at this checkpoint; direct pre-edit copies are pinned in task-9h5-root-before.json. After source readiness, root may add one Container editor/storage identity assertion and make the exact accepted resolver/constructor edits; only that old Container graph test may construct its disposable SQLite engine (no PostgreSQL claim), while other source tests forbid engines. Early refund companion has a disjoint read-only concrete preflight only; no metadata/schema/head changes while current-head9h5 SQL is pending. No PG owner or new companion parent assigned yet.


### Root implementation checkpoint: social integration, exclusive SQL and disjoint follow-ups

Read full host-fix independent review: Important closed,114/no-engine,50refs preserved; accept boundedsource readiness (whole-five329/388stillFAILED98). Root then ran actual-main14RED/zeroengines plus added Container identity assertion1RED/oneSQLite-memory/zeroqueries/disposed. Exact2productionedits wiretypedexisting resolver andsameSQLeditor/storage. Exact129GREEN1.42s; independent129/1.53s,59refs+13native9h4runtime preserved, exactsource/testreversals andscopedquality pass. Accept rootintegrationSOURCE only; noSQLclaim.

Fresh statichead stillfinancial_corrections_a1 parentcampaign_drafts_v1 hash2e94...; priorcorrectionrelease05:25:36zero andnonewPG. Transfer EXCLUSIVEPG tod01_filter_source_audit forNEWsocial_editor_pg.py/test_social_editor_native_pg.py atthatunchangedhead. Freshownerbaseline05:41:46zero; firstfocused99/13.75s passes3socialPGfiles. Root readfullproposed79filecohort andaddspermanent10-caseHTTPstatussafetyrepro, final80explicitfiles: prior9h4+129socialsource+socialPG+9h2history/verification/linking+13factory/config+2safeerrorfiles. Whole7runtime/2helpers separately, unchangedexact98, noSQLresultmock/newexclusion/headchange. Finalfreeze/zerorelease/freshindependentSQLreview required; sourcebugchanges onlyafterconcretereport/rootcoordination.

Read full approvalcompanionpreflight32c426...: approved2applicationfiles +NEWpurehelper/test mayproceed whileallSQLrepositories/models/schema/metadata/migrations/head frozen; noapplicationinfrastructureimports/currentContainer coupling. Grant thatAPPLICATION/PUREphase torefund_approval_application. Narrowfixturecompatibility separatelyauthorized: directarchivecorrection_commands.py andtest_correction_service.py; addtwofactkinds andcase-matches-basedlinkselection only; exactearlytestexpectedknownrefusal supersededbyoriginalstableintent/newapprovalsuccess withalloldimmutablehistoryassertionsretained. NULLcaseclient/orderownnewRequestmayuse authenticatedscope/currentadvertiser onlywhenbothroutingclientsmissing; nofallbackforprivatecase/operationreads, noorphanhistoryattachment, retainallnonNULLbindings/nativefirst. Actualarchivedwriter/SQLguardcompatibility remainslater.

RootfoundsocialUIrawexceptiondetailandcachedprivateaccountsaftercurrentdenial. Grantsocial_editor_authority_ui ONLYsocialmoduleumc-shell.js +NEWauthoritybrowserfile, andexact5oldrawSyntheticdetailassertions→existinglocalizedfailuretext, preservingallretry/input/pending/normalizationassertions. SyntheticChromiumonly; noexternalE2E/DB/provider. Actual38-caseRED36failed/2URLcontrols→38GREEN; fullsocial/designcarryandindependentreviewpending. UIchanges areoutsidebackend80cohort andmustnotbeclaimedunchangedbyit. NootherworkerPG. No migrationparent orschemaimplementation released. Fullgoal remainsactive.

### Root acceptance and analysis refresh: social editor and approval application

Read the complete final independent social SQL, authority-loss UI and retained-approval/order reviews. Static recheck `task-current-analysis-source-recheck.json` confirms every recorded source/artifact reference in the three selected freeze groups still matches; migration AST remains 120 revisions, sole head financial_corrections_a1, parent campaign_drafts_v1. Accept only their bounded results: social SQL exact80-file1978, seven complete runtime modules1716/1751=98.0011422044546%, separate helpers306/311,50 distinct actor/writer pairs including14 observed waits; authority-loss UI70 synthetic Chromium cases; approval APPLICATION/PURE342, two complete runtime modules657/658=99.84802431610942%, separate helpers170/172. These overlapping selections are not summed. Social SQL release06:08:08.909463UTC records zero remaining private schemas/client sessions/runner processes and no later database call. No PG owner is assigned by this analytical checkpoint.

The approval Important retained-order finding is closed: every retained approval/match binds to the actual genuine request/case/order; mutually matching foreign-order records are insufficient. This is application source acceptance only. Current corrections SQL repository still lacks approvals/match_approvals, and there is no companion schema/model/migration or archived-writer upgrade proof. Old PhaseA425 remains historical old-writer SQL evidence, not current support for the new application facts. No new schema revision/parent, PG grant, compensation, ingress, provider action, flag, commit or deployment follows from this record.

Root separately repaired five old helper typing errors in fakes.py, factories.py and services.py; focused mypy3, bounded default/NULL/time/markup behavior with zero engines, Ruff/format3 and default-policy source mypy504 passed as recorded in task-root-helper-types-* and task-root-current-source-mypy.log. The1978 run predates these three changes and is not presented as a post-repair rerun. The source mypy result has three untyped-body notes and does not replace a new whole-branch make fix.

Latest explicit user steering is “Проверить и учесть в анализе”. Current work for that steering is analysis only. Fresh root fetch still has main=origin/main6505af277fd01ab83fc7f2ba5ba07eba81bd2396,0/0; primary user metadata and untracked files are untouched. Root and two read-only independent checks confirm the design ZIP24files/187653bytes, main0/24 and feature24/24 byte identity. Tokens/local references are complete; README contains three stale paths, and both Cyrillic font files themselves lack ӘәҒғҚқҢңӨөҺһҮү. Feature already provides whole-kk system fallback. Main-only analysis remains20tasks:12partial/8without the requested new scenario. Feature analysis remains20tasks2local/15partial/3none and30criteria14local/13partial/3notpassed. Update D01/R05/T01 prose and source evidence only, preserving these statuses and the main/feature distinction. File/data/link checks are in task-current-analysis-final-check.json; no new TypeScript/render or device acceptance is claimed. Full goal remains active and incomplete; this analytical delivery does not authorize applying additional product changes.

### Root resumed goal: additive approval storage and genuine archived writer

The preceding analytical turn is progress: it reconciled the actual archive/main state and corrected authoritative feature evidence, including the unsupported current approval SQL boundary. The explicit goal continuation now resumes implementation. Fresh static root release `task-6ca2-root-companion-release.json` rechecked all120 revisions, sole head financial_corrections_a1/parent campaign_drafts_v1 and exact historical schema/model/migration plus accepted application service. Assign new revision financial_refund_approvals_a1 with parent financial_corrections_a1. Existing historical correction schema/models/migration and original archive/proof/P01 sources remain unchanged.

Release the accepted additive SQL companion to approval_companion_sql: two new schema/model modules, new assigned migration, one models.py registration import, exact SQL repository fact read/write changes and new dedicated PG/helper files. This agent alone owns PostgreSQL after a fresh clean baseline; no other worker/root queries it. Follow the complete accepted design/preflight, including exact new approval/link provenance before application, genuine complete-legacy validation, current real capture/source/bundle checks, deferred event/receipt timing, final metadata hook order/partial creation, parity with Alembic and populated-safe downgrade before any destructive change. Keep existing component/cumulative/liability/pending/wallet economic predicates. Do not loosen legacy provenance to accept synthetic Request-as-Review. Any existing fixture semantic supersession needs explicit narrow coordination preserving its substantive financial assertions.

Release only NEW tests/helpers/correction_legacy_writer.py and tests/unit/test_correction_legacy_writer_loader.py to approval_archived_loader. Execute all three exact manifest-pinned archived modules under context-lived unique private module names with local import substitution, isolated from canonical modules/global builtins. API: archived_correction_writer() exposes ports/service/repository modules; instantiate archived commands and implementations. Test actual isolation, tamper refusal and cleanup with zero engines. The loader alone does not prove SQL compatibility; the exclusive SQL owner executes the genuine oldhead request/review/observation/match upgrade and preservation sequence.

Actual oldhead behavioral RED has been observed and read by root: task-6ca2-awaiting-match-red.log/run.json records1 failed in5.34s because a retained synthetic Request-as-Review awaiting match committed without the expected authority rejection, with no application. Clean owner baseline has zero clients/private schemas. This confirms the absent retained-match guard; no missing table/import is counted as the defect. Task5 forward guards and Task6 monetary/source-transition integration remain later coordinated work. No compensation, public ingress, provider/send, flag, commit, push or deployment is granted by this companion release.

### Root bounded acceptances and disjoint delivery retention repair

Read the complete independent three-helper typing review13960ad0...: fresh ordinary scoped mypy3 with separate cache, Ruff/format3, bounded default-now/explicit NULL/datetime identity/in-memory persistence and markup tuples pass with five engine guards and zero requests. Exact function-body/AST preservation and current hashes are verified. Accept only these typing/helper semantics, not a new whole-suite or PostgreSQL run. The historical1978 remains pre-repair evidence.

Read complete portable-loader report/freeze and independent review75e32f5e...; root rechecked all30 recorded references. Accept only the loader: exact16 fresh guarded pure cases, whole helper54/54, standalone report/JSON98 pass, source-layout mypy with MYPYPATH=src/explicit package bases and normal imported diagnostics. Its initial missing-module result is availability only; actual old-class routing1RED/15controls is the behavioral failure repaired by archive-local import substitution. Canonical modules/builtins remain unchanged and private keys clean up through nested/error contexts. Actual SQL upgrade remains the companion owner's task.

Root found the accepted Task5 finish-only retention gap still present: PaidSelectionDelivery._source rethrows selection_scope_changed_retry_required before _finish retains already-actual transport I/O. Release exactly _finish plus a NEW pure test to delivery_finish_retention, with no other source/factory/schema/PG scope. Direct before source d3c73a3f... intentionally supersedes to8b6400d5...; all other14 methods and bytes outside _finish are unchanged. Only the exact scope error is handled at finish as unavailable, retaining exact accepted outcome/reference/attempt with applied=False, no accept/fulfillment/economic retry/new User. Prepare/begin refresh, existing fence/idempotence and unknown failures retain their behavior. Author5RED/4controls became49 fixed pure checks. Root independently read complete source/test/SQL call context and repeated49/0.49s,0engines/PG imports. No material source finding. Exact whole runtime141/175=80.5714285714%, standalone report and JSON both exit2 at unchanged98; retain that failed gate. Accept source readiness only; distinct-backend actual retention and existing meaningful SQL carry remain required.

The companion owner was explicitly informed of that one disjoint intentional source supersession. It alone retains PostgreSQL; no root/other worker query follows. Delivery author may now author only NEW test_selection_finish_scope_retention_pg.py and, if needed, NEW selection_finish_scope_pg.py by reading fixture sources, without PG imports/collection/engines/credentials/query. It must exercise an actual manager-set discovery/reread race with real statements/PIDs, not an injected expected exception. No actual PG grant follows from source authoring.

Root narrowly releases companion test compatibility changes after actual existing3file12failed/106passed: direct archives first. In test_correction_commands_pg.py update only the captured/newapproval assertions and obsolete early-refusal expectation to same-intent/newapproval success while preserving original evidence/proof/noapplication assertions. Keep synthetic tests/helpers/corrections.py::approved_match frozen as negative/old storage evidence; use a NEW genuine helper for current-head economic carry. In test_correction_sources.py only the retained-routing and projection-corruption local imports/calls change to that genuine helper; projection test's two version=2 values become current.version+1 because genuine history has four events, preserving next-event semantics and every assertion. In test_correction_schema.py only the helper binding changes; the forged-capture test may extend its raises boundary to outer commit because retained matches are now guarded before application. Preserve all money/component/capacity/rollback assertions and every unrelated function. This is an explicit semantic supersession, not removal of financial tests or a provenance relaxation.

Root read the new companion schema/model/migration and identified a concrete legitimate-order mismatch: the application's source_capsule carries ALL order ground IDs sorted by UUID, while initial SQL expected only selected IDs ordered by item. Exclusive owner has actual referred/covered-absence application positives and aligns SQL to the existing capsule without changing the selected-ground source seal. Full physical required-table checking and partial/repeated metadata guards are required before final acceptance. Task6's later original-assessment source transition remains separate; no ground check is dropped here.

### Companion integrity and current verification checkpoint

Fresh read-only reviewer approval_companion_review inspected current source and saved task-6ca2-independent-source-checkpoint.md; it is not acceptance or a PG grant. It confirms the exact old economic guard replacement and root's historical pins. Its initial suspected omission of physical-proof table prerequisites was withdrawn: BASE_TABLE_MAP already includes that table. Preserve the explicit trusted test-clock boundary; public commands cannot choose recorded_at and fresh application checks its trusted UTC clock, while SQL validates the retained timestamp against due. No DB clock/GUC policy is invented.

Actual Container INSERT fault tests demonstrated two result_state_hash failures, two previous_state_hash failures and a later broken non-review-prefix failure on default application capsule validation. Owner repairs authenticate dense prefix versions, state/source identity, recomputed state hashes, predecessor hashes and monotonic retained observation sets. Historical retained-match validation checks its original prefix, while new application checks the current prefix. Physical-proof key consistency has one actual bad-key RED with a valid control; use canonical source/account/direction/reference hashing, without changing configured namespace recognition or frozen proof identity. These are current companion integrity fixes, not historical data rewrites or Task6 compensation.

Root explicitly permits only one private damaged-legacy negative: an actual old producer's intent.request_id becomes NULL under the single private immutable trigger, with genuine-before versus damaged-after snapshots distinguished, exact one-field difference and actual enabled trigger state before commit/upgrade. It is damaged historical-data evidence, never genuine complete old producer output; full genuine controls remain unmodified all-three-archive executions. No other private trigger scope follows. Root also authorized the third test_correction_sources helper alias change in test_observation_survives_savepoint_but_outer_failure_rolls_back after reading the complete function; its economic-savepoint retained1 and outer-rollback0 assertions remain unchanged.

Delivery future PG source is frozen at3f9db2ae... in NEW test_selection_finish_scope_retention_pg.py; root read the complete source and underlying real lock/source/job paths. It is one genuine manager expansion before final User locks, not a wait claim. It uses a declared fixture writer with existing repository and User/order locks, not a new production manager flow. AST/Ruff/format/mypy passed; no import/collection/execution/PG followed. It remains outside the companion cohort and waits for a later explicit PG grant.

Default-policy root source mypy passed507 files with the same three existing untyped-body notes, task-6ca2-root-source-mypy.log. This is a source-quality checkpoint while SQL strings are still being finalized, not a frozen whole-branch make fix. The live companion candidate run is exec86729/pytestPID2460638, recorded in task-6ca2-whole-cohort-first-live.json:17 explicit files combine the342 pure carry, five original SQL files, new companion SQL and accepted loader unit tests. Whole six runtime files and six helpers are measured separately at unchanged98, with existing migration omission policy retained and actual migration upgrade/downgrade executed. Root verified that PID live by /proc without DB use; a wait timeout is not a terminal result or a reason to restart it. Final pass/fail/coverage/freeze/quality/zero-resource release remain pending. Approval_companion_sql alone retains PostgreSQL. The next reviewer remains read-only until root explicitly hands over the final frozen SQL stage.


### Root final companion freeze and independent SQL handoff

The first552 run is terminal550pass/2newfixturefailures, not a timeout or a passing test gate; its artifacts stay intact. The new helper observation amount was fixed to the real scope.bundle.total_minor without a production change. Fresh same17-file552 finished209.49s, no skips/warnings; four standalone CLI98 gates pass: runtime1442/1461=98.6995208761%, helpers655/661=99.0922844175%. Whole6runtime and6helper files are measured separately; unchanged migration omission is disclosed with actual direct up/down tests. Root read the final run/log/raw totals, quality and42-reference preservation audit. An additional normal-import scoped mypy5 (MYPYPATH=src, explicit-package-bases, no silent override) passed at root and author; the earlier silent check is preserved rather than renamed. Root static preflight confirms32 cohort/policy hashes and42 protected hashes,121 revisions/sole financial_refund_approvals_a1 with exact old parent.

Author explicitly released PostgreSQL to root at07:19:26.839745UTC: zero private schemas/other clients, all710 observed backend identities gone, both runner/pytest process groups ended, observer closed/engine disposed. No later owner DB calls are allowed. Root freezes the actual final-run bytes in task-6ca2-root-review-freeze.json, SHA79bb5714e820f36c67670ecacff2fcd7630839f883d46dfb2d4812f2a1f5b3e8. The author may finish text-only report/freeze artifacts without touching source. This root source freeze prevents a report-editing delay from holding the SQL review idle; the final author report still must be read before a verdict.

Transfer EXCLUSIVE private PostgreSQL to approval_companion_review for a fresh independent exact same552 cohort, six whole-runtime and separately six-helper coverage/standalone gates, ordinary scoped quality, preservation and actual authority race evidence. No frozen edits, broad suite or extra cohorts are granted. The one extra isolated fresh-schema approval-only populated-downgrade probe is allowed because the existing with_match=False case shares a session schema containing other linked facts; its refusal is not yet isolated approval-only proof. Keep that probe outside552 and label it separately, with real no-link preconditions, unchanged tables/guard/facts on refusal and clean schema teardown. No new malformed history, trigger disabling or product policy follows. Fresh resource baseline/release and exact provenance limits (test clock, damaged legacy fixture, orphan absence) remain binding. No live financial/provider/send/flag/commit/push/deploy action or Task6 compensation is included. Delivery worker remains source-only until a separate later grant.


### Root resource transfer: delivery finish actual SQL

Independent companion exact552 finished209.31s; all4 CLI98gates pass and frozen hashes match. Its separate isolated fresh-schema genuine approval-only downgrade probe passed5.26s with1approval/0links/0matches/0applications across the whole schema, no destructive/mutating statement before refusal, identical tables/functions/triggers/fact-text snapshots both inside and after commit. Root read the complete probe source and actual log/run/release; final companion report is text-only preparation and still must be read before bounded source/SQL acceptance. PostgreSQL explicitly returned to root at07:31:16.156661UTC with zero clients/private schemas, all1070 author/independent union backend identities gone, both independent processgroups ended, observer closed/engine disposed. No further reviewer DB calls.

Root read the full task-6c5-forward-guard-current-preflight.md (bc85127b...) and accepts it as preparation only: live_funding raw case IDs need trusted semantics; gross/source separation cannot ship without ordinary guards; full prospective User/wallet discovery must precede existing producer and P01 locks; read-only payout hints need writer/source-family parity; Task6 exact pre-issue witness/expected whole-capture ground transition remains separate. No code implementation or Task5 completeness follows.

Transfer EXCLUSIVE PG to delivery_finish_retention for its already frozen NEW test_selection_finish_scope_retention_pg.py (3f9db2ae...) and accepted finish-only source/pure fix. Fresh clean baseline first. Prove actual RED with the exact directly archived before-source d3c73a3f... function in a clearly isolated test import/temporary in-process function context; never rewrite runtime bytes or SQL results and always restore canonical runtime identity. Meaningful RED must be the genuine manager scope expansion after actual accepted provider I/O, not an import/table/harness failure. Then current-source GREEN and one fixed explicit meaningful existing delivery SQL/runtime carry plus unchanged49pure regression cohort. Freeze the cohort before execution; full175-statement current runtime file at unchanged98, actual driver/statement ordering and retained unapplied outcome/no accepted delivery/no item mutation/no second send. Separate expected RED from actual GREEN; no new repeat unless concrete failure. Scope is one real interleaving, not a lock-wait claim.

No source/test/schema/model/migration/factory/config changes are granted in this SQL phase. A concrete harness defect must be reported/coordinated before editing a frozen test. Quality/preservation, final report/freeze and fresh terminal cleanresource release are required before independent actual review. Private UUID schemas and DSN secrecy rules remain unchanged. No full forward guards, Task6 compensation, provider/send/flag/commit/push/deployment are included; observed Bot I/O is the declared test adapter boundary.


### Root bounded acceptance: additive approval storage

Read the COMPLETE final independent SQL review b498250dad90e781f45ff6a6e69ed3a47454070a0aed3b0a47007f7ba64a2580 and freeze59fa3324281005cb5dd156eb0c9ec30ce2bed9016143c22a8c2e4ac7cda0d29a. Root rechecked all58 source/policy/fixture references, all36 independent/root/author artifact references and all180 preserved prior artifact references. Actual isolated probe before/after snapshots compare equal; root independently checks captured statements contain no mutation/destruction before refusal. Fresh552/209.31s, runtime1442/1461=98.6995208761%, separate helpers655/661=99.0922844175%,4gates0/quality,60 observer-backed native authority races and separate approval-only probe support bounded acceptance. No remaining Critical/Important finding. Accept only additive approvals/exact links/current SQL repository/metadata+migration/genuine archived writer upgrade; preserve current head121 and all frozen old sources. Task6, signed ingress, direct fresh orphan SQL, full30/25/5, wholemakefix, devices/providers and R05 completion remain open. Root evidence is task-6ca2-root-bounded-acceptance.json. PostgreSQL is already exclusively assigned to delivery_finish_retention; no root query followed.

The feature canvas now reflects this accepted storage rather than claiming approvals SQL absent. Main-only canvas stays unchanged on6505af2;20 feature tasks retain2local/15partial/3none and30criteria14local/13partial/3notpassed. U01 archive verification stays24/24 feature versus0/24main. Only R05/T01/next-step prose changed, no JSX/layout/component or TypeScript/render claim.

Root also read the COMPLETE task-6c6-compensation-source-transition-preflight.md. Accept as preparation: current UUID-tuple preparation cannot carry a strict pre-source seal; post-issue DTO or plausible immutable originals alone do not witness the validated pre-state. A future explicit typed preparation value and SQL-visible authenticated immediate pre-source/deferred exact-completion witness need concrete bounded design and a NEW separately assigned additive revision after the actual coordinated head. No revision or implementation is assigned by this note. Normal strict source path stays intact. Original issue spans all capture items and thus all-order ground IDs; selected item/due/intake/assignment/delivery fields may not be omitted or mutated under a ground-only allowance. Known absence/potential remains distinct from missing coverage and zero journal. Pending-only atomic compensation before successful original receipt, full ordered discovery, rollback and existing work/legacy/P01 guards stay required. No circular call into the consumer, singleton/session.info capability or posthoc expected-ground subtraction is accepted.


### Root delivery retention actual SQL result and independent handoff

Actual SQL archived-before RED is1failed/5.18s at archived_finish308 → actual repository manager reread150 → selection_scope_changed_retry_required after genuine test Bot acceptance. Canonical method restored in finally; runtime bytes stay8b6400d5.... First fixed83passed/16.60s, whole171/175=97.7142857% FAILED exact98 despite native default-rounded report/JSON0; this false-positive display is preserved, and a precision2 report correctly exits2. No source or policy weakening followed. Existing tree has no meaningful carry for retained_observe exact/conflicting fields, so root released exactly NEW test_paid_selection_outcome_replay.py:1exact replay+4 distinct field conflicts after a real accepted-result producer, not an invented new bug.5pure/0.04s,0engine/PGimports; no artificial missing-job test.

Fresh fixed union old83+new5 gives88passed/16.68s, whole174/175=99.4285714%, no exclusions, only missing line318. Native report precision2 and nativeJSON both0; JSON lacks precision option, so exact Fraction174/175>=49/50 is separately mandatory. No CoverageScript wrapper, config/omit/threshold change or fake CLI precision support. Root read fullNEW5, complete independent source checkpoint e6d2f5d5..., actual RED log/final result/raw evidence and checked driver199551!=199552, exact sorted initial/new User sets, no late User after order mutex, actual locked manager reread,2actor+1writercommit, unapplied accepted outcome/noacceptedINSERT/noitemUPDATE. No new source finding.

Author returned EXCLUSIVE PG to root at07:50:28.658946UTC, task-6c5-delivery-retention-sql-resource-release.json:0clients/private schemas,all745 backend identities gone,10ownedPIDs/3groups ended,observer199748closed/engine disposed,94refs exact. Root statically rechecked94refs and freezes actual final88/source/evidence before author text-only report editing in task-6c5-delivery-retention-root-sql-review-freeze.json. Transfer EXCLUSIVE PG to approval_companion_review for fresh exact88/whole175runtime/precision2report+nativeJSON+exactFraction, quality/preservation/actual PID/retention inspection and terminal cleanrelease. No runtime/test/schema edits, no extra RED restoration needed, no broad suite/repeat without concrete failure. Read final author report/freeze when available before verdict. FullTask5forwardguard,Task6,actualManagerServicewriter,lockwait/provider/device/wholemakefix acceptance remain outside. Root made no DB call.


### Root bounded acceptance: delivery retention; current continuation

Read COMPLETE independent delivery SQL review c61487000ea57e7b946886d8165b85c23c14cfc874d02c60de86239fcca3574b and freeze708d149f760386a2ca6a02dea1c05ef48e7c21077879f9531ac17f5caa432014. Rechecked94 unique frozen refs,30 independent artifacts and60 author artifacts; root independently walked raw actor199890/writer199891 traces for distinct PIDs, sorted2/3 Users/no late User, noaccept/itemwrite and2+1commits. Fresh88/16.80s, whole174/175=99.4285714%,0exclusions, precision2native report0/nativeJSON0 plus exactFraction pass, scopedordinaryquality4. Accept only finish-time actual-result retention and its carry; no broader Task5/Task6/sprint claim. Root evidence:task-6c5-delivery-retention-root-bounded-acceptance.json SHAe60c39646051b8ff081930cc624b4676d68c12846014863311adf620bb6df1dd. Reviewer returned PG07:57:08.949804UTC with0clients/schemas/all1054unionbackends and4ownedPIDs/group gone,observerclosed/engine disposed. Root now owns the idle PG slot; no next owner assigned or DB query made.

Latest analysis steering is fully handled: ZIP checked, main0/24 versus feature24/24, font/README limitations retained. Fresh final fetch still main=FETCH_HEAD6505af2/0-0; user dirt unchanged. Feature canvas now also records bounded delivery acceptance in R01/T01 and removes its completed verification from next-actions. Source/data check task-6c5-analysis-final-check.json confirms20task/30ACIDs+statuses and U01 unchanged,2/15/3tasks and14/13/3AC; no TS/render/device claim. Main canvas remains2a91ff28...; feature is5a92e30b56c58addd5a74f940029b2aa12ec281dda2a6bbfaa5a2453ad98a235.

This goal turn made progress: additive approval storage and bounded delivery repair accepted through fresh independent actual SQL; two exact next-source preflights completed. Full goal remains active/incomplete. Next internal work is Task5 shared live guard semantics and authenticated case/correlation loader (raw live_funding case IDs are not finalized blockers), then complete ordered discovery/producer/P01 reader parity. Task6 requires the separately designed explicit typed pre-issue token and SQL-visible immutable expected original-assessment transition before atomic pending compensation; no new revision is assigned. Do not rerun accepted552/88 absent changed sources/failure. Current condensed pointer is /tmp/umc-full-sprint-reports/task-current-continuation.json. Full wholemakefix and30/25/5 remain pending, as do other20-task/30AC gaps and genuine external facts. No blocked/paused/complete goal status follows.


### Root Task5 shared guard/source execution release

Prior goal turn is progress: bounded companion552 and delivery88 independently accepted, source preflights complete. Root alone owns the idle private PG slot after07:57:08 cleanrelease. Execute Task5 shared guard core and authenticated case/item correlation inline: NEW correction_funding_guard.py, NEW pure and PG guard tests, and only corrections.py::live_funding plus its private helpers. Historical schema/models/migrations, all other repository functions, existing fixtures and accepted delivery/P01/producer source stay frozen. Archive exact current repo f36c12... before change. First actual SQL REDs: rejected request without any bank fact must clear its live case blocker; a report for a real selected subset must not widen to sibling positions; rejection after actual report must keep the blocker. Pending/approved unresolved cases, early known order/intent, unknown correlation and corrupt replay require explicit controls. No new migration, gross-validator relaxation or production integration until common facts/guard are correct and verified. Full Task5 producer/barrier/P01-reader integration and Task6 remain open.


### Root Task5 common guard execution checkpoint

Actual old live_funding discriminators are2fail/1control and expanded12fail/5controls, with exact old method identity restored and runtime bytes unchanged. Current19-file union is587pass/213.59s; whole two runtime files348/353=98.5835694051%,5missing/0exclusions, nativeprecision2report0/nativeJSON0+exactFraction pass. Seventeen new actual SQL cases and18pure cases establish current case/report membership semantics and the read-only failclosed guard. AST preservation confirms only live_funding changed plus3private helpers;57other held source refs unchanged. Smaller failed98 gates and initial module-availability error remain distinct from behavioral RED. Source-only helper applications are declared fixtures, not Task6 producers. Ordinary globalformat962/lint and source mypy508 pass. Focused2306backend identities/recorded PythonPIDs ended and0clients/schemas. Root report:task-6c5g-core-report.md; result:task-6c5g-final-result.json.

No new independent review: the two delegated workers reached account usage limit. Prior companion/delivery acceptances are not widened. Required wholemakefix is live runner2503476/make2503492/group2503492,8513selected nonE2E tests with actual privatePG, unchanged98/config. Six campaign draft/API failures have appeared; full terminal diagnosis/whole exactcoverage/cleanrelease pending. All source/test bytes stay frozen while it runs. Do not restart a live process after a missing observation. Task5producer/barrier/reader integration andTask6source transition/compensation remain open; this is progress, not completion.


### Whole gate diagnosis and bounded repairs

First required makefix terminal:8487pass/7fail/19skip/600deselected,106warnings,999.13s; exactwhole37700/38291=98.4565563709% passes but testgate fails. All966source/policy files unchanged,13938observedbackend identities gone,0clients/schemas, recordedPython/make/runner ended. Actual raw JUnit/logs retained as task-6c5g-whole-*. Six campaign failures share CampaignFrozenMap rejecting actual SQL MessengerType StrEnum; signedTG/MAX return503. Newpure3 discriminator:2fail/1control0.10s →3pass0.05s after canonicalizing StrEnum.value only; unsupported nonstring Enum stays unavailable.

Actual SQL new positive creator/owner valid referral_payout_rate eachfails after enumfix:Decimal from unrelated entireUser row was also frozen. Root releases campaign_review.py::candidates only to project actual required actor(user_id,status,telegram_id,telegram_usable) andinviter(user_id,status) fields; no broad Decimal/type relaxation or financial edit. Bothactual SQL cases then2pass5.16s. Canonical enum behavior still needed for selected status/profile enums. Archivebefore bothruntimefiles retained.

Seventhfailure is after successful distinctPID/SKIPLOCKED/rollback assertions:process_once bounded100batch doesnotreach currentfixture behind prior sharedschema retainedevents, retrycount stays0. No productionclaim defect. Ruling: use existing shared fixture.__wrapped__(request) in a function-scoped private schema for this two-test globalqueue module, as existing digest/payout modules do; keep everyoriginal assertion/runtimefunction/queuepolicy intact. This repairs test isolation, atcost2extra isolated migration setups. No source filter, batchlimit increase or history cleanup.

Freshfixed25-file union601pass39.92s,2existing record_property/xunit2 warnings, whole2runtime383/384=99.7395833333%,1missing/0excluded; nativeprecision2report0/nativeJSON0 and exactFraction pass.814backend identities/recordedPythonPIDs ended,0clients/schemas, frozenpins unchanged. Globalformat964/lint pass; ordinarymypy508 passes same3untyped-body notes. Evidence task-6c5g-whole-fixes-*. No new independentreview because accountusage limit; bounded authorverification only. Root now starts separate task-6c5g-whole-final.py requiredwholemakefix, preservingfirstfailed artifacts. No further runtime/test edits whilelive. Task5integration andTask6remain open.


### Queue-fixture follow-through and current whole gate

Secondwhole (task-6c5g-whole-final) produced2concrete neighboring deliveryruntime failures after601focusedpass: ownrequest retry0 instead1 and pending insteadfailed after4bounded batches. Isolatingconcurrency removed incidentaldrainingofsharedqueue, exposing the same independentfixture defect in test_financial_delivery_runtime.py. Root stopped pytest once withSIGINT to collectactualtracebacks; no timeout/restart inference. Recorded4313pass/2fail/1skip/600deselected,569.42s partial; wholecoverageNULL andno fullcompletionclaim. Runnerterminal583.92s,unchanged968pins,9853backendidentitiesgone,0clients/schemas. Firstfullfailureandpartialresultsremainunchanged.

Ruling extended to the neighboring globalqueue runtime module only: sameexisting fixture.__wrapped__(request), functionscopefreshUUIDschema, everyexistingfunction/class AST unchanged. Bothmodulefixtures preserve allqueue/batch/retry/money/rollback assertions andproductionfunctions; no financialruntime change. Searched allPG testsusing globalclaim/processonce andreadlegacy/registered/notice ownershippaths; broadenedfocusedcarryincludes those, clientconsumer andhistoricalcapture. Fresh30-file union616pass/60.58s,2existingxunitwarnings; whole2changedruntime383/384=99.73958%,native2gates0/exactFractionpass,1320backendidentitiesgone/0clients/schemas. Format964/lint/diffcheckpass. Root now runs separatetask-6c5g-whole-current.py makefix, preservingallprior failed/interrupted artifacts. No further source/test edits whilelive.


### Root current whole gate terminal; Task5 remains partial

Freshcomplete makefix:8499pass/19skip/600deselected/107warnings,1059.71s; exact37709/38295=98.4697741219%,exit0. Format964 unchanged/Ruffpass/ordinarymypy508pass same3notes. All968source/configpins unchanged duringandafter. Four whole runtime files individuallypass98:corrections325/330,guard23/23,campaignports334/335,campaignSQL49/49. Skipreasons18externalTelegramtoken/1genericDATABASE_URLmigration; actual privatefinancialPG/migrationsran. No device/providerclaim. All14555backend identitiesand127Python/make/runnerPIDs ended;0clients/schemas,observerclosed/enginedisposed. Rootowns idlePG. No repeat absentchanges/newfailure.

Currentreport task-6c5g-current-execution-report.md recordsreal REDs, firstwholefailures, concrete secondpartialinterruption,616pass focusedrepair,exactcoverage/provenance/limits. No freshindependentreview: delegatedworkersaccountusage errors. Common guard is authorverifiedfoundationonly, not fullTask5/Task6. Root readcurrentdelivery_source: ordinaryValueErrorrefusalsalreadybecomeinvalidsource; only exactscopeRetryescapesandacceptedfinishrepairretainsit. New task-6c5g-integration-follow-through.md recordscompleteprospectivescope/factory/selection/replacement/P01 traps asread-onlypreparation, no newsourceorSQLacceptance. Task6typedpre-issueSQLtransition/remediesstillopen.

Featurecanvas now records587guardcore,616preview/queuecarryandfresh8499wholegate. R05/T01/M02 proseupdatedonly;20task/30AC IDsandstatuses unchanged2/15/3tasks,criteriaunchanged;maincanvas2a91ff28... unchanged. Featurecanvas08323bb2363159fbd3e3b8c27f38fd8236178b541edec02e48fc3589d20feb46. ZIP/U01findingsunchanged. NoTS/renderclaim. Work is progress; entire20-task/30ACgoalnotcomplete. ExistinggoaltoolreportedusageLimitedduringhumancontinuation; no goalstatusmutation/resetwasperformed. No commit/push/deploy/provider/send/flagactivation.
