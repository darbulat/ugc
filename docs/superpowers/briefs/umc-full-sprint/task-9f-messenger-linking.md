# Task9f — secure MAX → Telegram account linking

Status: bounded design/contract audit for root review, 2026-10-24. Only this brief is written. No production, schema, migration or test edits, credentials, live messages, provider calls, activation or full gate. Checkout9e has been independently rechecked; this stage addresses its advertiser-only MAX identity gap. It does not create an invoice or authorize a payment.

## Recommended decision

Keep the existing MAX canonical User as the owner. A currently authenticated MAX advertiser requests a short-lived linking challenge, opens its server-generated Telegram bot link, authenticates there as the actual native Telegram sender, then returns to MAX and explicitly confirms the displayed Telegram identity. Only that final MAX confirmation can attach an unused Telegram ID to the same original User UUID.

Linking grants the Telegram identity access to the existing canonical account and its current roles, subject to the normal current authorization/financial gates. The MAX confirmation must state that account-access consequence, not describe this as merely sharing a payment link.

A nonce proves possession of a challenge, not ownership of the MAX account. Opening a forwarded link can only propose the actual Telegram sender for MAX to inspect. It never links automatically. Equal numeric IDs, matching handles, display names, phone strings, Instagram names, browser fields and a Telegram callback result are not identity equivalence.

Never merge users, move or delete an apparently empty account, detach an existing messenger ID, replace another Telegram ID, or rewrite orders, roles, referral relationships, registration dates, grade history, wallets or money. An existing separate Telegram canonical account is a conflict requiring a distinct reviewed resolution, even if it has no selected role or visible balance.

## What the current code actually does

- `miniapp/auth.py` validates platform-specific initData with the corresponding configured token. `principal.py` adds duplicate-field/size checks and a 24-hour freshness limit with 60-second future skew. These are separate from canonical-user resolution.
- `miniapp/api.py::_ensure_user_and_get_id` calls `set_user` for an unknown external ID and auto-sets a missing MAX country. It cannot be the Telegram proof resolver before linking. Even a read through the normal Mini App bootstrap can therefore create the unwanted second User.
- Telegram `start.py::_start_command` calls `set_user` before referral parsing. MAX `/start` shares it. A dedicated linking `/start` handler must run before ordinary start/registration; a reserved linking-prefix error must terminate there rather than fall through to signup or referral handling.
- The native Telegram locale middleware looks up an existing user and updates its handle only when one exists; it does not create an unknown user. It can remain on the linking route.
- `users.telegram_id` and `users.max_id` are separately nullable and unique. The immutable internal UUID is used by advertiser/creator profiles, orders, referral bindings, financial wallets and historical sources. `messenger_type` is not proof that the other identity is absent: an actually linked MAX-created User can legitimately remain `MAX` while acquiring a Telegram ID.
- `SqlAlchemyUserRepository.save` merges an entire User model. A new attach operation should perform a narrow compare-and-set of `telegram_id` (and explicitly approved identity metadata) under a User lock, preserving every unrelated field, rather than saving a stale full entity.
- The creator Instagram flow already carries authenticated MAX sender metadata in a verification code, then calls `InstagramVerificationService._try_link_max_account` → `UserRoleService.link_max_account`. That low-level helper can clear another row's `max_id/max_chat_id`. It is not an attach-only general linker and must not be reused for9f. This audit does not approve that detach behavior for a new general flow or change the legacy creator workflow.
- Checkout9e already handles a genuinely shared canonical User: MAX status generates a configured-bot `pay_{order}` handoff; Telegram authenticates its own sender and checks the same UUID/order owner. That path should continue unchanged when both IDs are already bound.
- Both production webhook applications support configured ingress secrets. MAX currently permits an absent secret for its legacy endpoint. The proposed new native Telegram proof capability requires its configured verified Telegram ingress; it must not accept an unauthenticated webhook body as an identity proof. MAX commands in this design use signed Mini App HMAC, not the optional-secret MAX webhook path.

## Platform facts checked in primary documentation

Telegram private-chat `start` payloads use ASCII letters/digits/underscore/hyphen and allow up to 64 characters; following the link supplies `/start <payload>`. A short opaque base64url token fits without a user ID or order ID in the URL. [Telegram deep linking](https://core.telegram.org/bots/features#deep-linking).

Use the native message's actual sender and private chat, from a verified bot update. Message sender information is not supplied by the linking request body. [Telegram Message](https://core.telegram.org/bots/api#message). Telegram Mini App proof, if a separate future entry is added, must validate server-side initData; initDataUnsafe is not authority. [Telegram Mini App validation](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).

MAX documents server-side HMAC validation with its own bot token, duplicate-parameter rejection, and Unix-seconds auth_date. Its Bridge recommends invalidating sessions after one hour; the repository's shared 24-hour helper is therefore not an automatic choice for this more sensitive capability. [MAX validation](https://dev.max.ru/docs/webapps/validation), [MAX Bridge](https://dev.max.ru/docs/webapps/bridge). MAX `openLink` requires a real user click and opens an external browser; returning to MAX must not be assumed automatic. [MAX openLink](https://dev.max.ru/docs/webapps/bridge#windowwebappopenlinkurl).

The TTL, request limits and confirmation policy below are application recommendations, not platform guarantees or statements about payment finality.

## User and identity flow

1. **Create from MAX.** Validate recent MAX initData before resolving the external ID. Use a read-only existing-user lookup, not an auto-create principal. Require the current canonical owner to be active and have an actual advertiser profile; re-read that the signed MAX ID still belongs to it. A bound Telegram ID returns truthful `already_linked` and keeps the existing checkout handoff. A different desired binding is not supported by this flow.
2. **Issue one challenge.** Persist the owner UUID, original MAX external ID, trusted bot/config scope, nonce verifier, server issue/expiry times, request identity and active pointer in one transaction. An operation-key replay returns the original result; a new key does not create another active challenge. No messenger/network I/O occurs inside the transaction.
3. **Explicit external open.** MAX shows the server link with a clear instruction to return and inspect the proposed Telegram identity. It calls `WebApp.openLink` only on the user's click. No automatic cross-app navigation or payment opening.
4. **Native Telegram proposal.** A new high-priority, private-chat-only `/start lk1_<token>` handler validates the reserved payload, actual non-bot sender, configured bot identity and verified ingress. It does not call ordinary start, set_user, registration, role or referral logic. A brand-new Telegram visitor remains without a separate canonical User. Unknown/expired/revoked/malformed reserved payloads are handled safely here too, without signup fallback.
5. **Check eligibility and record the claim.** A Telegram ID already bound to the same owner means the pair is already linked. A Telegram ID bound to any other User is a conflict; do not detach or infer that account is disposable. An unused ID may make one immutable proposed claim, containing its actual ID, minimal native display-name/username snapshot and source fact. The first proposal cannot be replaced by another sender holding the same token. The Telegram reply says only that this Telegram identity is proposed and MAX confirmation is still required; it exposes no MAX profile, order or financial details.
6. **Explicit MAX confirmation.** MAX reloads owner-scoped server status and displays the proposed Telegram numeric ID plus the native name and optional handle as descriptive text. Nothing is pre-confirmed. Confirm is bound to the displayed immutable claim ID and expected challenge version, not a body-supplied Telegram ID. The same original MAX identity must still authenticate as the original canonical owner, still active and eligible. Re-check expiry, claim, current IDs and conflicts under locks.
7. **Attach atomically.** In one caller transaction, set the unused Telegram ID on the original MAX User and append confirmation/attachment facts while consuming the challenge. Unique constraints remain the final concurrent-owner guard. No new canonical User or financial/referral/history mutation is part of this transaction. Only after commit report `linked`.
8. **Refresh checkout.** MAX explicitly refreshes actual owner checkout status. The existing Telegram pay handoff now resolves to the same canonical UUID. Linking itself must not issue/retry an invoice, enable finance flags, grant an override or claim payment success.

The retained MAX owner may already have wallets, paid orders or historical grades. Attaching a new authenticated external identity to that same UUID preserves those records. A separate Telegram User with any or no visible history is still a conflict; no history scan can prove it safe to merge or delete.

## Proposed service and API contract

A dedicated `MessengerLinkService` and attach-only repository port should own create/read/propose/confirm/revoke. Keep the financial checkout service and its read/payment contracts separate.

Proposed MAX-only routes under `/miniapp/api/messenger-links/telegram`:

- `POST /challenge`: strict signed MAX envelope and bounded `operation_key` only. Returns the current challenge or already-linked result.
- `POST /status`: strict signed MAX envelope; optional opaque challenge ID, still owner-scoped. No external/canonical owner IDs from the body or query.
- `POST /confirm`: envelope, operation key, challenge ID, immutable claim ID and expected version. No username, Telegram ID, target owner, bool proof or admin override field.
- `POST /revoke`: envelope, operation key, challenge ID and expected version. Revokes only an unconsumed challenge; it cannot detach a completed identity.

No public unsigned or ordinary-principal Telegram claim endpoint is needed for the first version. The Telegram `/start` adapter invokes a private service command with native identity/source metadata after actual ingress authentication. An optional future signed Telegram Mini App claim route would need a separate non-creating external-identity resolver and its own review.

Public MAX result: `state` (`awaiting_telegram`, `awaiting_max_confirmation`, `linked`, `expired`, `revoked`, `conflict`, `already_linked`, `unavailable`), opaque challenge/claim IDs, version, server issue/expiry times, action capability, minimal proposed identity, and a safe reason. Return the launch URL only to the current original MAX owner while the challenge is live. Never expose key/hash, bot token, another canonical UUID, wallet/history details or conflict-account contents. Foreign challenge IDs and an identity remapped to another owner get the same safe not-found response.

All new envelopes forbid extra fields and query authority. For linking writes, recommended MAX initData age is at most one hour plus the existing 60-second skew; validate duplicates/encoding/size before HMAC and read-only lookup. This is a scoped policy choice, not a silent global change to the existing principal helper. An expired auth session requires reopening the Mini App.

## Nonce, configuration and replay

Recommended challenge TTL is ten minutes; expiry only invalidates this identity proposal. It does not release or expire any checkout/payment authorization. An owner can explicitly revoke an unconsumed challenge and request a fresh one; replacement appends revocation and issuance atomically, never leaves two active owner pointers, and never revives the old token.

Use an opaque 256-bit token and a stored SHA-256 verifier, not a short human code. A 43-character unpadded base64url token with prefix `lk1_` is 47 characters, below Telegram's 64-character limit. Parse exact ASCII grammar/length; require the configured exact HTTPS bot host/path, and keep the token out of logs, analytics, referrers and error text.

A hash-only random nonce cannot be reconstructed when the create response is lost. Recommended recovery is a dedicated server-keyed HMAC-SHA256 token derivation over a canonical, domain-separated challenge context containing a CSPRNG salt, challenge UUID, owner UUID/original MAX identity, trusted bot scope and issue time. Store only its verifier, salt/context and key ID; an authenticated same-operation replay can reconstruct the same live launch URL. This requires a new dedicated, validated secret key of at least 32 random bytes in actual secure server config and an explicit key ID; do not reuse provider, payout-requisites, admin or bot-token secrets. Propose an independent `MESSENGER_LINKING_ENABLED` defaulting false; it never changes financial flags. Missing/invalid key, trusted bot scope or required ingress config disables new challenge creation without partial state. Rotation keeps the required key only for live challenge recovery; an unavailable old key causes safe unavailable/revocation, never a guessed token. Pure hash-only random tokens with explicit replacement are an alternative only if root accepts the recovery UX.

Exact operation/source replay is deterministic. Reusing an operation key with a different challenge/claim/version conflicts. Native replay of an already observed valid proposal returns the historical decision without reopening consumption/expiry; a different sender cannot take over that proposal. A lost confirm response is resolved by same-command replay and current server status, never by issuing a new challenge or attaching again. If the bound IDs subsequently change through another reviewed path, replay must not report that the old pair is still currently linked.

Apply bounded per-current-MAX-owner issuance/confirmation limits and per-authenticated-Telegram-sender invalid-token/claim limits. Suggested initial issuance cap is five per hour; root must approve operational limits. Unknown tokens reveal no owner or existence detail and produce no canonical-user mutation. Rate limiting/config failure affects linking only, not durable paid receipts.

## Proposed persistence and locking

No schema is created in this audit. A later reviewed additive migration would need immutable challenge/claim/command/event facts plus small active owner/challenge and active Telegram-claim projections. Record actual server observation times and actual native source identifiers; do not backdate messenger proof or call it Instagram verification. Statement-level UPDATE/DELETE/TRUNCATE guards protect facts, with idempotent source uniqueness and changed-payload conflict. One active challenge per owner and one active proposal for an unused Telegram ID must be enforced transactionally, not by browser state.

A linking command discovers scope with nonlocking reads, then locks the original User with FOR UPDATE first, the actual advertiser-profile row with KEY SHARE, then link-identity advisory coordination and challenge/projection rows. No wallet, order, creator-profile or financial history barrier is acquired. Re-read current owner/MAX/TG bindings, status and expiry after locks. Any User FK facts are inserted while that original User lock is already held; a proposed unregistered Telegram identity has no separate target-User FK.

For two MAX owners proposing the same unused Telegram ID, consistent identity coordination and a unique active-claim guard select at most one; the loser cannot overwrite or consume the winner's claim. An existing different canonical Telegram User is only read to reject; do not acquire or mutate its money graph. Reclaiming an expired foreign active-claim projection must not introduce a late lock or FK check on its owner User after identity/challenge locks: reference its existing challenge for audit and change only the non-User reservation under identity coordination, or fail safely until an owner-ordered cleanup completes. Final narrow attachment is a guarded UPDATE plus the existing unique Telegram ID index. Concurrent ordinary signup may win that index; handle the integrity conflict with a savepoint/whole-command rollback, never `set_user`'s broad rollback-and-adopt helper inside a caller transaction. Append a truthful conflict outcome only in a valid transaction; no success fact may survive a failed attach.

Ordinary metadata updates or legacy creator linking can change ownership while a challenge is pending. Every write and sensitive status read must re-check the original MAX binding and the actual current IDs. Revoked, expired, changed-owner, disabled/blocked and conflicting claims fail closed. The generic User repository's full-model merge is not the attachment port.

## Brand-new visitor and registration race tradeoff

The normal linking journey avoids a second User by consuming the reserved native `/start` before ordinary signup and by not opening the normal Telegram Mini App bootstrap before completion. After successful attachment, a normal Telegram `/start` or `/api/me` resolves the existing MAX UUID.

If that person independently opens ordinary Telegram registration in parallel, it may legitimately create a separate canonical User before final attachment. Recommended minimal scope is to fail linking safely and require separate review; never delete/merge it based on apparent emptiness. A stronger pending-Telegram reservation that also blocks all ordinary canonical-user creation would reduce this friction, but needs coordinated changes to every external-ID writer and a typed pending response in the auto-creating principal/bootstrap. It must not fake authentication as the MAX owner before confirmation. That broader reservation behavior is an explicit root decision before implementation, not an implied permission to change all registration paths.

## UI and native behavior

Add a small owned linking view/controller reached from MAX checkout's current linking-required state; do not rebuild shared screens. Keep the real already-linked checkout handoff working. Show waiting, exact proposed Telegram identity, explicit Confirm and Reject/revoke, expiry, conflict/manual-support and current linked states in all five locales with safe text DOM, 320px light/dark and existing native back controls. Names/handles are display snapshots; the immutable Telegram numeric ID identifies what is being confirmed.

HTTP-unknown create/confirm/revoke retains its stable operation and visible uncertainty. Reopen/read status first; no auto-renew, claim, confirmation, detach, invoice request or payment opening. Bounded owner-only read polling may help when returning from Telegram, but stop when hidden, expired, terminal or unauthorized and retain an explicit Refresh button. Back navigation does not prove revocation. Telegram reply/send failure does not lose a committed proposed claim; the user can refresh MAX or replay the same native start. A success toast or bot send result is not the binding's source of truth.

## RED-first acceptance plan after root design approval

1. **Principal and native interception:** actual signed MAX HMAC with current token; stale/duplicate/ambiguous initData; wrong platform/token; existing-only lookup with no auto-create/country/role side effects. Actual native Telegram private sender/source; invalid secret, bots, groups, wrong bot, malformed/multiple start args. A brand-new `/start lk1_…` reaches the linking handler before normal start and creates zero new Users/referrals/FSM signup effects, including invalid/expired reserved prefixes.
2. **Real PG factory/atomicity:** actual MAX advertiser, unused TG ID, claim then explicit original-MAX confirmation yields one unchanged UUID with both IDs. Inject failure between narrow attachment and immutable receipt: all-or-nothing rollback. Rebuild actual factories and replay HTTP-unknown create/confirm/revoke; same key/context is stable and changed payload conflicts. Missing crypto/bot/ingress config creates no partial challenge.
3. **Conflicts and history:** existing separate TG account with and without visible money/role data is refused without detach/delete/reassignment. Same canonical pair stays usable. Preserve created_at, profiles, country/language, role/admin, direct referrals, original immutable Instagram/registration observations, wallet amounts, ledger counts and order owners byte-for-byte except the explicitly attached external field/approved identity metadata. No wallet/history locks or events are invented.
4. **Real concurrent connections:** two claims for one challenge, two owners for one TG ID, two active creates for one owner, confirm versus revoke/expiry, duplicate confirm, owner/MAX/TG binding changes, and ordinary registration versus final attach. Assert distinct backend PIDs and at most one legal attach with truthful loser/no partial facts. Follow the selected registration-race policy; never silently adopt a separate canonical row.
5. **Source/expiry/privacy:** forged body target/owner/verified fields rejected; equal numeric MAX/TG IDs are unrelated; foreign MAX cannot read/revoke/confirm; forwarded/stolen token cannot finalize without original MAX confirmation. Exact native source replay is idempotent; changed source conflicts; time advancement never revives consumed/revoked proof. Key rotation/config loss is honest unavailable. No token/hash/private account history appears in API/logs or the Telegram reply.
6. **Production native boundary and old flows:** real Telegram webhook secret validation and actual adapter fields with synthetic sends only; handler reply timeout cannot undo committed proposal. Ordinary `/start`, referral, creator-IG verification and the already-same-canonical9e pay path regressions remain green. No claim of durability for an external polling runner not present here.
7. **Actual browser assets:** MAX user click opens only the server launch link; no optimistic linked state; display/confirm the actual proposed TG snapshot/version; no response-body identity substitution; same-command unknown recovery, reload/back/expiry/revoke and conflict states. A deliberately different Telegram claimant is visibly shown and does not become linked until MAX explicitly consents. After actual server binding, refresh existing checkout and use its authenticated handoff; no invoice request is sent by linking. Five locales, 320px dark/light, safe DOM and native controls.

## Root decisions and remaining boundaries

- Approve the minimal fail-safe parallel-registration policy or explicitly widen scope to a cross-writer pending identity reservation. Both must refuse separate-account auto-merge/deletion.
- Approve the dedicated key management/reconstructible-token recovery approach, ten-minute TTL, scoped one-hour MAX freshness and operational rate limits. No secret is available or invented by this design.
- Assign narrow native/router/principal/UI ownership and confirm a future additive migration parent only after design approval; this audit creates no migration or implementation plan/code.
- A conflict can provide a truthful support/manual-review state, but a general account-merging/rebinding/admin-detach workflow remains separate. Linking and any manual resolution must not change financial rollout/provider/legal defaults or payment authorizations.

This brief recommends a concrete attach-only flow and identifies its registration/config policy decisions. It does not approve implementation or mark full O01/UMC acceptance complete.

## Root design decision — 2026-10-24

Accept the minimal parallel-registration policy: a separately created Telegram
canonical User is a safe conflict, never merged/deleted/detached. Accept the
dedicated validated server secret/key ID, ten-minute challenge TTL, scoped MAX
one-hour freshness plus60-second future skew, and five new issuances per current
owner per rolling hour. Exact replay/current-active reads do not consume a new
issuance. Define a bounded per-native-sender invalid-token/claim limit in the
implementation plan before code; it must not create Users for rate-limit keys.

Never persist a clear token or launch URL in command/event/audit facts. Store a
safe command receipt and frozen derivation context/verifier; reconstruct the
launch URL only for the still-current original authenticated MAX owner while
the challenge is live. Consumed/revoked/expired replay returns historical receipt
separately from current state, without resurrecting the URL or claiming a former
pair is currently bound. No token in logs/error text/analytics/browser persistence.

Native proof uses actual private Telegram sender and trusted actual bot scope;
the production endpoint already rejects absent/wrong webhook secret. A body
boolean/header copied into a service command cannot prove verified ingress.
Reserved lk1_ payloads, including malformed ones, terminate in interception before
ordinary User creation/registration/referral. Actual Telegram reply failure does
not undo a committed proposed claim.

Design accepted for a later bounded implementation assignment. No source/test/
schema changes until the current payout fix/recheck and shared makefix checkpoint
finish. The future migration parent must be coordinated against actual head then.

## Execution-plan handoff — plan only

The detailed plan is `docs/superpowers/plans/2026-10-24-umc-messenger-linking.md`.
It treats the root decision above as accepted, separates persisted safe receipts
from live derived URL responses, and requires the actual coordinated stable9ga
head as the future migration parent. The proposed native abuse bound for root
review before code is20 new reserved-link attempts (valid or invalid) per actual
native sender and trusted bot per rolling ten minutes; exact source replay is
exempt and the counter creates no canonical User. No source/schema/test edit,
database call or gate is authorized by this documentation handoff.

Legacy compatibility boundary: current `UserRoleService.link_max_account` can
clear a separate orphan row's MAX ID; an empty-orphan test does not prove this
safe when that canonical owns paid orders/wallet/history. The9f plan includes an
actual pending-challenge/legacy-remap denial regression and preserves the
original-MAX recheck. A separate full-goal compatibility audit is still needed;
no broad legacy merge/rebinding refactor is authorized inside9f.


Root plan decisions — 2026-10-24: approve20 new reserved-link proposal/invalid
attempts per trusted bot ID and actual native sender ID per rolling ten minutes,
with exact source replay exempt and no canonical User creation for counters. The
independent linking flag defaults off; safe history/current-binding reads and
reserved-prefix interception remain available while disabled, with no ordinary
registration fallthrough or new attachment. Preserve actual noncreating MAX
resolution and advertiser-profile barriers; no money/history locks. Root owns
central config/model/container/types/API/app/webhook patches. This worker owns
new modules/tests and the narrow linking UI/checkout/HTML/CSS. The shared gate
and root GO are still pending; actual9ga migration parent remains unassigned.

Execution checkpoint: the dedicated ReservedLinkMiddleware now precedes LocaleMiddleware in actual dispatcher setup. Reserved native starts therefore bypass even ordinary get_user/Telegram username synchronization and preserve separate canonical metadata; normal pay_ routing remains unchanged. Production webhook has its independent secret-validated pre-ACK interception. Real dispatcher active-support/native-pay tests prove this boundary.

Root-approved lock correction from actual PostgreSQL evidence: original owner User FOR UPDATE is acquired first, then advertiser-profile KEY SHARE, linking identity and challenge/projection locks. NO KEY UPDATE allowed an existing FK KEY SHARE holder to coexist until telegram_id unique-key UPDATE strengthened the User lock after role locks; the distinct-session regression observed that unsafe late upgrade. Stronger first-owner locking avoids this inversion. No foreign User, wallet, creator-profile or identity-history locks are added.

Implementation checkpoint: root GO and actual PostgreSQL release occurred; `messenger_linking_v1` is the additive child of coordinated `financial_payout_contracts_v1`. Earlier plan-only/no-GO paragraphs describe their historical documentation checkpoints. The final read boundary also verifies immutable live challenge/claim history against active owner/Telegram projections; absence or mismatch fails closed without repair. Terminal/expired history does not require obsolete projection rows. Root review found and drove actual RED→GREEN for this projection-absence boundary and whitespace-only webhook-secret capability. The final scoped report records current evidence and limitations.
