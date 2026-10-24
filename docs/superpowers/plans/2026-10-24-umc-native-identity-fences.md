# Current messenger identity checks for financial requests

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the approved inline execution method. Steps use checkbox tracking. Implementation and database slots require a separate root release.

**Goal:** Authorize each financial request against the same current messenger identity and canonical account throughout its existing transaction, and preserve separate accounts during creator linking.

**Architecture:** Carry a small authenticated principal explicitly from the signed gateway to the existing first User authorization barrier. Validate current native mapping there before permissions, replay, private reads or mutations. Keep financial payloads, journal facts and existing lock order unchanged. Account linking returns a distinct conflict when two canonical accounts already exist.

**Tech Stack:** Existing Python3.13, FastAPI, application ports, SQLAlchemy/PostgreSQL, signed Telegram/MAX requests, pytest/sysmon.

**Spec:** Existing sprint ownership/privacy requirements; accepted findings in `/tmp/umc-full-sprint-reports/task-9h-identity-compatibility-audit.md`; current9f attach-only design; existing9ga/9gb financial contracts.

## Constraints

- No live account, transfer, provider request, message, feature activation, deployment or commit.
- Root coordinates source ownership and exclusive PostgreSQL access. Historical slot assignments are recorded in the main sprint plan; every new database phase requires an explicit fresh release. Task1 and Task2 independent source/SQL checkpoints are accepted and PG released. The bounded9h3 intake/collaboration slice is also accepted. The bounded9h4 partner/selection/summary snapshot source/SQL slice is now accepted. The main sprint plan records the active exclusive PG owner and every later release.
- No migration is required for these identity checks. Do not change frozen builders, historical facts, monetary formulas or saved command payload hashes.
- No merge, detach, deletion or transfer of orders, roles, referral relationships, wallet/history or administrator authority between separate canonical accounts.
- All existing sorted User/wallet/item barriers remain in their established order. Do not lock an actor early in a gateway and then acquire other users in a different order.
- Existing9f/checkout native fences and9gb read-only typed principals retain their separate tested behavior.
- All user-facing copy has RU/EN/KK/BE/UZ variants and safe fallback. Notifications are tested with synthetic adapters only.

## Review focus

- A request's current native mapping must be checked at the existing actor barrier, independently of current role/status checks.
- Internal recipient-funding checks are distinct from authenticating the requesting actor; an admin's native principal must not be compared with the payout recipient.
- Authentication metadata is not an economic command field and cannot change old idempotency hashes or original receipts.
- Verification of an Instagram account and linking messenger accounts are separate outcomes; a linking conflict must not be presented as linking success.
- Unknown financial callers must not create accounts or change country as a side effect of a read or denied command.

## Task1: Explicit financial principal and defensive authorization checks

**Files:** Create `application/native_principal_ports.py`, `miniapp/financial_principal.py`; narrowly modify `application/services/payout_service.py`, `miniapp/payout_api.py`, `application/payout_errors.py`, `application/services/rate_override_service.py`, `application/override_ports.py`, `infrastructure/db/repositories/rate_overrides.py`, its memory adapter and `miniapp/override_api.py`. Root owns central main-API wiring. Final names follow the actual existing override port layout.

- [x] Define an immutable trusted server principal containing canonical UUID, validated platform and external native ID. The HTTP body cannot select these values. Resolve only existing accounts after configured HMAC and shared freshness validation; never call `set_user`, set country or grant roles.
- [x] Keep the current gateway and application transaction boundary. Pass the principal explicitly to financial application methods. At the already-held first actor User barrier, require both the same UUID and current platform-specific native ID, then retain all existing role/status/resource checks.
- [x] Preserve the minimal immutable request lookup needed to discover the complete sorted actor/recipient User set. The native check precedes replay, decryption, private response and mutation after that complete barrier; it does not require an early actor lock. Preserve existing `FOR NO KEY UPDATE` strength. Introduce a separate typed financial resolver protocol; do not change the generic UUID resolver or the new payout-read principal.
- [x] Payout commands validate this relationship before replay/private input use/money. Older payout reads, safe recovery, protected history and audited reveal perform the same check under their existing actor barrier. Pass no requester proof into `_clear`'s independent recipient checks. Trusted internal callers may retain their current API through an explicit optional principal argument; every signed HTTP path must supply it. No body boolean or missing HTTP proof permits bypass.
- [x] Preserve original economic payload encoding and stored receipts. Cross-platform replay by the same currently bound canonical owner keeps the same business key/payload meaning. Authentication metadata stays outside the command hash and is never stored as initData/token.
- [x] Rate-override authority facts include the native fields needed for the same comparison after its established ordered User barriers. Keep current administrator, recipient, policy, time and version validation. No late User/wallet lock or reader snapshot substitution.
- [x] Use exact known public error codes, constant unexpected errors and no-store responses/validation. Private details and authentication input never enter response/log exception text. Preserve current9ga exact money strings and acceptance behavior.
- [x] Write normal-behavior regression tests before the checks: current bound TG/MAX callers succeed; changed or absent current binding is denied before private output/receipt/event/money; unknown callers create no account/country; current admin/status revocation still denies; internal supported calls and old command hashes remain unchanged. Use existing synthetic adapters and actual router/service methods, without additional standalone security probe programs.
- [x] After the explicit root PG release, add two-session database tests for current mapping at the existing actor barrier and blocked concurrent identity updates. Keep independent PID evidence, bounded completion and unchanged sorted lock order. Run payout/override carry, scoped quality and fresh sysmon coverage at the unchanged98 floor; obtain independent review.

## Task2: Explicit separate-account conflict in creator linking

**Files:** Narrowly modify `application/services/user_role_service.py`, `application/services/instagram_verification_service.py`, existing verification result DTOs, `instagram_webhook_app.py` and existing localized text/notification seams. Do not introduce a general account-resolution workflow.

- [x] Apply the safe conflict policy whenever the MAX identity already belongs to a different canonical User, including an automatically created shell. Preserve same-canonical idempotence and a genuinely unused external identity attachment. Do not inspect a few balances and infer a separate account is disposable.
- [x] Document the compatibility change: automatic linking through a second canonical shell stops. The user receives a clear separate-account conflict; no claim that old orders or balances moved. A future manual resolution policy is a distinct task.
- [x] Produce a typed linking-conflict result instead of silently converting it into generic verification/linking success. Keep the actual Instagram verification result and code consumption explicit and separate; do not invent a successful messenger attachment.
- [x] Notify only the initiating user's validated recorded MAX chat through the existing result adapter, with safe localized copy and no other account's private details. A failed notification does not mutate account ownership or turn conflict into success. No live send occurs during implementation.
- [x] Test current same-canonical/unused identity behavior, two distinct canonical accounts, an original MAX-only account with existing business ownership, an account retaining another messenger, target already bound elsewhere, and notification failure. Verify original ownership/history/roles and all unrelated User fields remain unchanged.
- [x] Review external-verification availability as a normal correctness prerequisite: unavailable third-party proof must remain unavailable and must not be described as verified. Do not infer deployment credential state or add an alternative identity proof. Any behavior change here needs a separately reviewed explicit contract and ordinary regression tests.

### Task2 root decisions after independent plan review

Task1's bounded source/pure/SQL review is accepted (see the checkpoint below).
The following ordinary correctness/compatibility contract has independent review;
root has now released Task2 for source/pure implementation only.
No new identity-probe program or live configuration inspection is required.

**Attachment transaction and writes:** extend the user persistence port, actual
SQL user repository and memory adapter with a narrow attach-only operation and
its preparation barrier. A default port implementation must report unavailable;
it must never fall back to reconstructing and saving a whole User. Discover the
target and current MAX owner before locking, acquire the complete sorted User
set before profile/history/identity writes, then coordinate the native identity
and re-read current owner/target facts. A changed prospective set returns a safe
conflict/unavailable outcome or refreshes the whole transaction; it does not add
a late User lock. Keep the established User-before-role/history/identity order
compatible with9f and the profile writer. Preparation performs no attachment.

Both verification paths must take this barrier before saving profile/social
facts or consuming the code. Re-read the current valid code and profile after
the barrier; webhook confirmation rechecks that the actual fetched username
still matches the current profile. The fetch itself stays outside the SQL
transaction. Only after those checks may the same caller transaction confirm
Instagram, consume the code and apply a permitted attachment. A later unexpected
failure rolls back all of those writes together. A separate-account conflict is
an ordinary result, so it need not roll back a valid Instagram confirmation.

Verification preparation and attachment target the fresh `valid_code.user_id`
and the same valid `code_id`. They never select a second target by Instagram
username. Pass that expected UUID/code identity through the typed preparation.
The direct legacy URL-based wrapper may discover a target once, but freezes and
revalidates that same target under its barriers. Re-reads must use fresh selected
columns/RETURNING or explicit populate-existing semantics; ordinary cached ORM
getters do not suffice. The SQL path requires one active shared caller transaction
for preparation, current code/profile checks, confirmation, code consumption and
attachment. Missing transaction capability is unavailable before any write;
`with_optional_tx(None)` cannot silently split this into auto-committed sessions.

For explicitly supported in-memory callers, a bounded opt-in typed memory unit
of work may preserve the same confirmation boundary. Its default is unavailable;
SQL, mixed and unknown adapters cannot enter it. It must atomically rollback
the participating User/profile/code/social facts and their indexes on unexpected
failure without reverting unrelated concurrent work. Keep this local rather
than introducing a general transaction framework or copying arbitrary adapter
attributes. If that guarantee requires broader infrastructure, positive memory
tests may supply an explicit supported transaction fixture and no-TM confirmation
remains unavailable. Neither choice permits an arbitrary fake session to count
as an active SQL transaction. Record the chosen compatibility boundary and test
post-confirm failure, mixed adapters and the no-write unavailable outcome.

Task2 implementer's chosen bounded alternative: do not add a production memory
UOW framework. Confirmation without a transaction manager, or with an unknown
or arbitrary fake session, is unavailable before writes. Positive memory tests
provide an explicit supported typed transaction fixture over their actual
participating repositories; mixed/unknown adapters are refused. Record this
intentional direct-memory compatibility change instead of silently reintroducing
the old optional-transaction path.

Root factory ruling:the actual configured Redis branch selected a code adapter
outside the shared SQL transaction,so merely passing the same transaction
manager did not satisfy this contract. Root owns the narrow
`container/repository_factory.py` change:select the existing SQL verification
repository for new codes regardless of the legacy Redis argument. User/profile/
code/social facts share that SQL family/session manager. Keep the Redis argument
accepted and unrelated Redis uses/standalone adapter unchanged. Never add a SQL
participant marker to Redis or confirm across independent stores. No live Redis
read/copy/delete/migration occurs; existing pending Redis codes are not promoted
to SQL proof and require regeneration at a future rollout. No rollout is made
here. Root owns factory/container regressions and records the compatibility
boundary; direct mixed/unknown adapters still refuse before writes.

The allowed attachment updates only `max_id` and the validated recorded
`max_chat_id` on the target. It never overwrites username, status, country,
Telegram ID, roles or any financial field. Same-canonical attachment is a no-op,
including no username/chat refresh. A different existing MAX owner or a target
already bound to another MAX identity is a conflict. Preserve both accounts.
A uniqueness race becomes the same ordinary conflict through a bounded savepoint;
it must not abort already valid Instagram confirmation or clear the other owner.
Use a narrow conditional UPDATE with fresh returned facts, not ORM merge of a
stale domain User. The direct legacy link wrapper must obey the same preparation
and write contract. Later real-PG tests cover concurrent status/native updates,
same-canonical no-op, uniqueness race and unrelated-field preservation.

**Results and one-time code policy:** if Instagram confirmation is valid, record
it and consume its valid code once even when a requested attachment conflicts
or its optional linking service is unavailable. Return an explicit typed
`VerificationLinkConflict` or `VerificationLinkUnavailable` carrying that
verification outcome and the initiating recorded MAX chat; never coerce it to
a User or normal attachment success. Apply this to `verify_code` and the sender
method, their complete return unions, helper branches and webhook dispatcher.
No linking metadata retains the existing normal verification result. A missing
target User/current profile or no longer valid code fails before confirmation,
attachment and code consumption; it is unavailable/invalid, not verified. The
typed internal reason distinguishes missing service, missing target, target
bound elsewhere and separate canonical ownership without revealing another
account. Send only a clear conflict/unavailable notice to the initiating
validated recorded MAX chat for these link outcomes. Notification failure
does not change either committed result. Choose locale from the existing
initiator when available, otherwise RU; provide all five normal translations.
Retain the old optional phone enrichment only after a newly permitted successful
attachment, only from the validated recorded metadata and only when the freshly
locked blogger profile has no phone. A same-canonical no-op, conflict or
unavailable result never enters that branch or overwrites a concurrent phone.

**External-proof availability contract for separate review:** the webhook sender
path requires a configured API client, an actual successful profile response
with a nonblank username and a nonblank current expected profile username.
Absent client, unavailable response or missing either username returns
`VerificationApiUnavailable`, leaves the code usable and writes no confirmation,
social proof or attachment. Known nonmatching usernames retain mismatch, with
the code unused. This changes the old skip-comparison fallback and requires
ordinary regression assertions for each case. The direct manual-code method
keeps its explicit `manual_code` provenance and separate caller contract; it
does not become an alternative source of webhook sender proof. No deployment
credential state is inferred or supplied by this decision.

### Task1 accepted bounded checkpoint

The unchanged nine runtime files passed the builder's scoped677test gate with
99.15%sysmon coverage at98floor. After test-only additions, the final60PG cases
passed; the original reviewer independently reran all60 in38.09s, including54
completed two-session cases with distinct actual backend PIDs. All freeze hashes
matched before/after, and fresh release found0otherclients/private schemas/owned
processes with verification engine disposed. Independent report:
`/tmp/umc-full-sprint-reports/task-9h1-independent-review.md`.
This closes Task1's bounded source/pure/SQL review, not the whole shared gate,
Task2 attachment compatibility, broader callers or full-sprint acceptance.

## Task3: Finish bounded integration and record remaining callers

Task2 bounded source/pure/SQL is accepted after independent review. Final
builder gate: 5574 passed, one unrelated global-DATABASE_URL migration skip,
209 mandatory private PG cases all passed, 98.28496% across16runtime modules
plus the root repository factory at the unchanged98floor. Independent SQL
reran209cases in20.04s:42distinctPID pairs,37actual blocking waits and2real23505
savepoint cases. All39frozen entries matched; fresh zero-resource release
verified before root reassigned PG to9h3. Report:
`/tmp/umc-full-sprint-reports/task-9h2-sql-independent-review.md`.

The lifetime finding is closed by source and actual same-session/root/savepoint
regressions. Prior362/413pure-only and failed75.52%/60.90% coverage are historical
checkpoints. New codes use the existing SQL store; pending old Redis codes require
regeneration at future rollout, not a live migration. Legacy separate-account
attachment no longer remaps accounts, and actual native remap still invalidates
an earlier general-link challenge. Broader caller and whole-tree gates remain open.

The separately scoped9h3 intake/collaboration source/SQL slice is now accepted:
`/tmp/umc-full-sprint-reports/task-9h3-sql-independent-review.md` independently
repeated919 tests (125newPG,96existingPG,698pure/API), zero skips,
exact2160/2187 statements=98.765432%, with70actual waits and72distinctPID pairs.
All17current and10+3+23 preservation entries matched, scoped quality passed,
and a fresh02:58:34UTC zero-resource release completed. Only these four HTTP
paths and their explicit carry are accepted. The bounded9h4 private snapshots
are also accepted after `task-9h4-sql-independent-review.md`: independent1365,
whole14-runtime1708/1736=98.3870968%,52 completed distinct-PID nonlocking-reader
cases, quality22 and66 repository/18 evidence references preserved. Fresh
04:10:15UTC zero-resource release ended that ownership. Campaign/social/other
legacy contexts and the stable whole-tree gate remain open; only the main
sprint plan grants a later PG owner.

Root's read-only remaining-caller inventory is saved at
`/tmp/umc-full-sprint-reports/task-9h3-source-map.md`. The intake client barrier and separately reviewed collaboration
User-before-item preparation contract are now implemented and accepted in9h3.
Partner/selection/summary read snapshots are accepted in bounded9h4. Campaign
contexts, social editing and other unaudited legacy callers remain follow-ups. The source
map releases no runtime change and is not a complete legacy authorization audit.

- [ ] Source-map the same current-identity requirement for intake/collaboration and any newly authorized capability. Patch only explicitly reviewed callers in a separately scoped follow-up, preserving their own lock and authority contracts. Avoid ambient global authentication state or unrelated API refactors.
- [ ] Re-run actual signed TG/MAX normal/denied cases, private-response validation, old replay compatibility, payout/override/verification carry and required database tests after each approved source phase. Root runs the shared gate only after concurrent owners are stable.
- [ ] Report exact evidence, source ownership, compatibility changes and remaining limitations. A completed financial principal check does not complete account resolution, wider financial corrections or full20-task/30-AC acceptance.

## Planning evidence and boundary

This root-authored plan uses the already completed audit and current source contracts. Two attempts to delegate further planning were rejected by an automatic content check; no additional probe or implementation resulted from those attempts. This document adds defensive requirements only. It neither changes code nor marks the reported findings resolved.
