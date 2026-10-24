# Task 9g / P01 — real Mini App payout workflow

Status: read-only contract audit and proposed design for root review, 2026-10-24. No implementation, migration, feature activation, bank operation or provider call is authorized by this document. Only this brief was added. P01 backend is still completing its isolated gate; findings below describe the inspected source, not a completed backend review.

## Scope and evidence

Build the same supplied UMC interface in Telegram and MAX: a visible entry from the existing partner cabinet for every role, an owner flow from actual published requirements and explicit terms acceptance to encrypted requisites and available-only reservation, own requests/status, and a separate current-admin workflow for publication, the 72-hour queue, reasoned decisions, prepared manual execution, actual bank observations, protected history and audited requisites reveal. No instant payout, bank integration, tax/fee/minimum assumption, activation switch or legacy-balance conversion is added.

Read sources: approved `task-7-payout.md`, `task-7-checkplan.md`; canonical product HTML P01 and financial-v1 amendment; `miniapp/payout_api.py`; `application/payout_ports.py`; `application/services/payout_service.py`; `infrastructure/db/repositories/payouts.py`; frozen `payout_schema.py`; `secure_requisites.py`; payout factory/config; signed P01 PostgreSQL API tests; both actual HTML bridges, `umc-partner.js` and host control adapter in `umc-shell.js`.

The current bridges in **both** HTML templates use `/miniapp/api` and parse replies with `Response.json()`. New controller calls go through `window.__umcAppBridge.request`; it injects fresh host authentication for each request. Authentication must never be copied into controller storage. Reuse `UMCShell.syncControls()`, existing safe areas, keyboard handling, theme events, local fonts/logo and tokens `--bg`, `--card`, `--ink`, `--muted`, `--line`, `--line-strong`.

## Actual current backend contract

All routes are signed POSTs below `/miniapp/api/payouts`, reject query selectors and forbid extra body fields. The server derives actor identity from verified TG/MAX authentication. Own reads accept existing users in `active`, `pause`, `bot_blocked`; admin access requires the database user to be **currently active and admin**. Staff-manager association, role choice, `_me` flags or a submitted boolean do not grant payout-admin authority.

- `/requirements`: currently effective requirements or null. Public fields are `requirements_id`, `version`, `effective_from`, `terms_reference`, `required_fields`, `enabled`.
- `/requisites`: `operation_key`, `requirements_id`, `accepted_terms_reference`, exact `details` key/value map. Returns `requisites_id`, `requirements_id`, `masked_label`. Requisites are encrypted; required keys must equal the published field set. The mandatory set includes `recipient_name`, `bank_account`, `legal_status`; arbitrary additional approved keys are possible. The crypto contract bounds 30 fields, key length 64, nonblank values up to 2000 characters and encoded total 20000 bytes.
- `/request`: `operation_key`, own `requisites_id`, positive `amount_minor`, `currency: RUB`. It allocates only actual available journal funds, checks current requirements and safety, and returns the immutable request plus current state projection/masked destination. The request includes recipient/request/requisites/requirements IDs, amount/currency, `requested_at`, `deadline_at`; state has `version`, `state`, nullable `execution_id`, `block_reason`.
- `/list` and `/{request_id}/status`: own requests; status also permits actual current admin. Status states include `reserved`, `approved`, `blocked`, `executing`, `unknown`, `failed`, `paid`, `rejected`. There is no owner cancellation command.
- `/admin/requirements`: protected complete publication history. `/admin/requirements/publish` accepts operation key, expected latest version, future-or-current aware effective time, legal/terms/evidence references, reason, exact required fields and enabled flag. Disabled publication is a real append-only event, not editing an old row.
- `/admin/queue`: limit 1–100, oldest requests first, `overdue` from server clock and immutable deadline. It currently loads all requests, then filters to nonterminal or blocked rows and slices; there is no continuation or total. `/list` is also unbounded.
- `/admin/command`: operation key, request ID, expected version, `review|reject|start|escalate`, reason, evidence reference. Review/start require evidence; start requires approval and creates a committed execution ID/fence. An unsafe review/reject/start may return `blocked`, not the requested outcome. Escalation is deduplicated, only after the original 72-hour deadline, and never pays/releases funds.
- `/admin/result`: operation key, request/execution/fence/expected version, `paid|failed|unknown`, reason, evidence reference/hash, actual bank account/reference, optional observed amount/currency/aware settled time, `recipient_details`. It records an observation, then applies money only when the full frozen proof and current safety match. A 200 response with `unknown` or an unapplied observation is not paid. Historical paid/rejected state may stay terminal while retaining a later exceptional bank fact.
- `/admin/{request_id}/history`: protected events, intents, outcomes, settlements; excludes ciphertext/fingerprint/key ID. Intents contain the saved fence and origin bank account, allowing an actual operator to recover execution scope after reload. Owner status must never receive this protected bank/evidence history.
- `/admin/{request_id}/requisites`: explicit operation key + reason, current-admin check, audited reveal of the frozen recipient map, with `Cache-Control: no-store`. There is no owner plaintext read endpoint.

Both `FINANCIAL_CORE_ENABLED` and `FINANCIAL_PAYOUTS_ENABLED` gate ordinary mutations and default off. Own/admin reads and reasoned reveal remain possible while paused. **Recording an actual bank result is deliberately allowed through the ingress while paused**; the observation is retained with its blocked/unapplied outcome. UI must preserve this emergency reporting path and must not present it as authorization to make a new bank transfer.

## Contract changes needed before a usable UI

### 1. Readable immutable terms and field definitions

Current `terms_reference` is only a nonblank opaque string. Tests use visibly synthetic references; there is no payout document resolver or stored full text. The UI cannot turn such a string into an agreement or invent an HTTPS destination. Public requirements also expose raw field keys without the labels/explanations/legal-status options needed for additional fields.

Proposed approved contract: extend publication atomically with a **server-stored immutable payout terms document** (`document_id`, exact `content_text`, source `locale`, server-computed SHA-256, actual publisher/time) and field definitions (`key`, localized label, optional localized help; text input unless the actual publication provides permitted values). Bind that document and schema to the new requirements ID. No UI HTML/Markdown execution; display full text using `textContent`, preserve paragraph breaks, and display the actual document language/version/hash. UI chrome has five translations; legal text is not machine-translated or silently replaced by localized copy.

Public requirements must return the bound readable document/schema. Requisites acceptance must send the displayed requirements/document ID/hash plus the existing exact terms reference; after locks, the server checks all against the currently applicable publication before storing the snapshot. Acceptance is unchecked by default and explicit. A new policy requires a new acceptance; pending intent is never upgraded to unseen terms. The requirements ID continues to bind frozen requisites/request history to the document forever.

Admin publication form supplies actual full content, field definitions, legal/evidence references, reason and effective time, previews the same owner document, then explicitly publishes/suspends with expected version. This is a usable configuration path, not a permanent missing-document gate. Existing opaque publications remain honestly unreadable/unavailable for new acceptance until a current admin publishes a real document; no backfill or invented terms. This likely needs a new append-only companion table/revision coordinated after the actual current Alembic head; do not edit frozen `financial_payout_v1` or already-published facts.

### 2. Exact minor-unit wire format

`MAX_MINOR = 2**63 - 1 = 9223372036854775807`. Current API request models require strict Python integer `amount_minor`; response canonicalization retains integer money in request/status/list/history/results. Native `JSON.parse` already loses information before any `BigInt()` conversion. Local read-only Node proof: parsing this maximum as a JSON number yields `9223372036854776000`, `Number.isSafeInteger=false`, and `BigInt(parsed) !== BigInt(original)`.

Use **canonical decimal strings for every monetary wire field** in the payout boundary, including nested history/outcomes and immutable command replies. Domain/SQL remain integers. `Reserve.amount_minor` and optional result amount accept validated ASCII decimal strings and convert to Python int before constructing the domain command/hashing; preserve existing integer API clients only if compatibility is needed, while all new UI payloads use strings. Reject exponent/float/whitespace/plus/leading-zero/non-ASCII forms and overflow; result observations retain the domain's signed amount range rather than being silently clamped. Response serialization changes presentation only, never stored command hashes/history. IDs remain strings; bounded SQL Integer versions may remain JSON integers.

Browser amount input is `type=text`, `inputmode=decimal`, labelled RUB with at most two fractional digits; normalize comma or dot by explicit grammar, convert by string splitting/padding and `BigInt` range comparison. Never use `parseFloat`, multiplication by 100, `Number`, Number-based `Intl` formatting, or `BigInt` in `JSON.stringify`. Format the canonical string directly, as partner money already does. Example acceptance boundary: `92233720368547758.07 RUB` maps exactly to `"9223372036854775807"`; `.08` overflows and fails locally/server-side. Do not round fractions or impose a lower synthetic product maximum. If a host lacks required BigInt support, keep reads/string formatting and disable mutation honestly.

### 3. Own recovery and safe masked requisites

There is currently no masked own-requisites list and no own operation-result lookup. If `/requisites` commits and its reply is lost, the browser cannot recover its generated ID without resending plaintext. Do not store plaintext merely to replay it.

Add signed own-only `/operations/status` taking just `operation_key` (no actor/recipient selector) and returning `recorded` plus safe original action/result or an explicit not-recorded observation. Serialize against the same actor command barrier so an in-flight commit is not misclassified as absent; a network failure remains unknown. Whitelist safe result fields; never return payload hashes derived from secrets or raw input. Add signed own masked requisites listing (or include in the context): ID, requirements/document version, recorded time, masked label, server-derived usable/current flag. No bank account/name/legal status plaintext.

For owner requisites storage, persist only the key and nonsensitive displayed terms/context metadata; keep details in memory until submit, clear after response/navigation/pagehide. On unknown response/reload, recover the safe result by key, never resubmit secret details automatically. For reserve, persist an allowlisted pending record **before I/O**: stable operation key, requisites ID, canonical amount string, RUB and local format version. Partition by server actor ID and platform, never accept an owner selector from it; never retain init_data, names, details or form DOM. Explicit retry uses the exact original nonsensitive payload/key. No auto-submit on mount, focus, native event or timer; no replacement key while unknown. A status read may run automatically because it moves no money. If browser storage fails, do not send a reserve that cannot be recovered after reload.

A requirements change or stale result blocks new intent, but must not rewrite an unknown request's requisites/amount/key. Idempotent replies are original receipts, possibly older than current state; show receipt separately and refresh authoritative status before enabling another action. Never infer success from a lower available balance. Once a confirmed intent is fully reconciled, a separately labelled explicit “New request” may clear it and start a new key.

### 4. Server capabilities, consistent context and bounded navigation

Add a signed own `/context` read with server actor ID, `as_of`, explicit runtime pause/configuration reason codes, actual financial source/reconciliation state and exact-string available/reserved amounts when known, current readable requirements, masked own requisites and capability names. Missing/mismatched journal/wallet is unavailable/reconciliation, never a quiet zero. Known empty history may say no earnings. Reuse the proven partner read snapshot rules; no wallet upsert, writer readiness claim or eligibility implied by a display balance.

Status/admin request detail should return server-derived `allowed_actions`, current version and request-specific safe blockers. Compute from real current actor/admin/status, state, config, requirements, deadline and actual prerequisites; mutation still rereads all authority under existing locks. The controller must not duplicate payout authorization or hide the paused actual-result path. Read capabilities are hints as of the snapshot, not consent or a guarantee against later disputes. Protected reveal stays a separate audited command and retains its current-admin lock check.

Owner history/list, admin queue and protected history need consistent snapshot/as-of and deterministic ordering. Add bounded keyset paging/continuation to owner list and queue; current oldest-100 slicing cannot let an admin inspect the rest of an outstanding queue. Server computes overdue/remaining deadlines; exact 72 hours is not a “paid by” promise. Protected history orders events by version, intents by preparation time/ID and observations by recorded time/ID; exposes actual `applied` and review reason to admins. Return a current protected execution context (ID/fence/prepared time/origin account) via admin detail/history, never reconstruct it from text or caller form defaults.

Known error codes must be mapped to localized safe copy (auth/role lost, paused, missing key/requirements, changed terms, version conflict, insufficient available, dispute/debt, reconciliation, invalid evidence/duplicate reference). Do not dump raw server exception text into the page. Unexpected/network errors keep unknown financial intent and offer safe refresh. On 409, refresh state and require a new explicit decision where appropriate; never silently update version and replay review/start/payment.

## Screen design and actions

Use new `miniapp/umc-payouts.js`, `.umc-payouts` namespace and narrow empty screen mounts/defer in both existing templates. Expose `UMCPayouts.open()` and `data-payouts-open`; partner entry “Выплаты / Payouts” stays visible even if partner financial data fails, so own historical requests remain reachable. Optional `?view=payouts` / request UUID deep link is a navigation hint only; signed owner/admin lookup is authoritative. It must coexist with the existing assignment/selection/partner routing precedence, without bypassing registration/authentication.

Owner screen has a compact available/paused/reconciliation notice, “New payout request”, and own requests. No new role registration. The new-request flow is sequential:

1. Read actual requirements and full terms, display source language/effective version and explicit unchecked acceptance.
2. Enter the exact published requisites fields or choose a server-marked usable masked snapshot; no guessed tax/legal-status options. Save encrypted snapshot explicitly and show only its mask afterwards.
3. Enter exact amount, review amount/masked destination/terms and the reservation/72-hour explanation, then a distinct final **Reserve amount** action. A saved requisites snapshot alone never reserves funds.
4. Show actual request state, reserved amount, original requested/deadline times, safe blockers and refresh/history. Reserved/approved/executing means processing; only server paid means paid. Unknown/failed remains visible and never offers a second bank transfer. There is no fabricated owner cancel, payout provider, upload or support handler.

Current admins additionally receive separate entry points for requirements and queue, from server capabilities. Do not eagerly fetch protected queue/history based on `_me.is_admin`. Queue rows show exact amount/mask/state/original deadline/overdue; no export or broad recipient search. Detail separates safe request status, protected history, explicit reasoned reveal, and one selected command form. Review/reject/start/escalate use their saved expected version and a reason; review/start demand real evidence reference. “Prepare manual transfer” states that it only creates the frozen execution record and that money is handled outside UMC; no “Send bank payment” button exists.

Actual-bank-result form selects paid/failed/unknown explicitly and records actual evidence reference/hash, bank scope/reference, observed amount/currency/time and recipient details against the prepared execution/fence. Do not prefill the bank reference/evidence as proof or present an expected amount as an observed fact. Paid proof may be rejected for money application while its observation is retained: render `applied=false`/review required explicitly. Keep reporting available during an emergency pause for a previously prepared execution when server allows it. Paid/rejected history and later exceptions remain visible.

All admin secret forms, revealed details and their operation keys live **only in memory**; no session/local storage, URL, console, telemetry, HTML data attribute, clipboard convenience or file export of them. Do not persist `recipient_details`. Clear secrets on submit completion, close/back, account change and pagehide; request fresh reasoned reveal if needed later. After an unknown admin submission, read protected history/status before any further explicit attempt; reload discards the form and never reconstructs or auto-replays it. Render supplied text through element creation/textContent. Opaque evidence/legal references are displayed as references; they are not advertised as readable documents without an actual protected resolver.

## Responsive, locale and native behavior

Complete RU/EN/KK/BE/UZ UI/error/action/status copy, with coherent RU fallback for unknown locale; document content retains its actual published language. Mint section, existing rounded UMC cards/type scale and supplied local brand assets; use existing semantic danger/notice tokens instead of a new visual brand. At 320px, one-column forms, wrapping identifiers, full-width actions and definition lists; admin history is stacked expandable records, not a horizontal table. Money is unbroken within a wrapping value container. No secret fixture values in published screenshots.

Every input has a visible label/help/error association; terms checkbox is keyboard accessible, status uses polite live region, failure uses alert, focus moves to screen heading/error summary. Show busy state and disable duplicate submissions. Native MainButton mirrors only the currently visible real form's final action; no primary selector on inactive tabs or multiple command forms. BackButton goes to the actual prior screen, clears secret forms and retains only allowed unknown reserve intent. Browser fallback has the same visible buttons. Existing TG/MAX adapters, theme changes, safe-area bottom inset and keyboard-resized viewport remain authoritative; do not introduce direct SDK payment/clipboard/bank APIs. Manual real-device native proof remains separate from mocked browser evidence.

## Proposed implementation/check plan after approval

- [ ] Coordinate the narrow backend/API changes above with the P01 owner/root before source edits. Announce a new terms companion migration only after the actual head and published immutable schema are confirmed. No bank/notification/provider code or activation change.
- [ ] RED actual PostgreSQL + signed TG/MAX contract tests: full immutable terms/publication and exact acceptance; changed/revoked requirements; current admin loss; owner-only masked requisites/operation recovery; paused history and actual-result retention. Prove all amount fields round-trip `2**53-1`, `2**53`, `2**53+1`, `MAX_MINOR`, signed exceptional observed amount/null; strict malformed/overflow values fail without rounding. Original idempotency hashes and receipts must survive string serialization.
- [ ] RED consistent context/source-unavailable/missing wallet/known-empty states; authoritative capabilities, version/role/dispute changes; owner cannot query foreign IDs or ask for admin/recipient selectors. Queue >100 requests is pageable without omissions/duplicate effects; 72-hour boundary and escalation remain the original deadline.
- [ ] RED Playwright on both real templates/assets with API interception only: owner full terms→unchecked acceptance→secret save→review→reserve→reload/history; store response lost recovered by key without stored plaintext; reserve abort after commit/reload exact pending payload/key; requirements changed while pending; rejected/stale/unknown/error paths; never automatic money retry or new key.
- [ ] RED admin browser flow: server capability visibility; actual publication; paged queue, reasoned review/reject/start; protected history/reveal; actual paid/failed/unknown with unapplied observation; result reporting while paused; 409 refresh without replay; role loss clears protected UI. Spy all browser storage/navigation/console and assert requisites, recipient_details, init_data and admin secret payloads never appear. All form buttons/native controls agree and cannot trigger an inactive action.
- [ ] Complete five-locale 320px light/dark coverage, TG/MAX native MainButton/Back/theme/keyboard safe-area checks, browser fallback and malicious display text. Capture and inspect owner confirmation, unknown reserve, admin queue/reveal-cleared/result-review states using visibly synthetic bank data only; redact/avoid secrets in screenshots.
- [ ] Actual ASGI GETs serve exact new asset bytes from both webhook apps without lifespan/live bot startup. Carry existing design/social/collaboration/partner/selection/summary/campaign/checkout browser regressions; scoped Ruff/format/mypy/node syntax and unchanged >=98% backend floor with sysmon coverage. Root coordinates full shared gate and fresh independent review.

## Audit boundary and handoff

No production source, static asset, test or migration changed for this audit, and no payout action/gate/full test run occurred. The only executable check was a local Node JSON precision demonstration. Numeric transport, readable document publication, safe operation recovery and authoritative capabilities are prerequisites to implementing the complete UI, not hidden client-side substitutes. Root review should settle this contract scope before implementation; backend P01 gate remains independently owned. Full sprint/M02/F01 goals remain open.

## Root design checkpoint and sequencing

Root accepts the concrete UI prerequisites above as the implementation design,
without enabling any payout or inventing legal content. Implement in three
reviewable steps after the current P01 state-authority fix and independent
backend review:9g-a exact decimal-string boundary, actual immutable readable
publication/acceptance and own safe recovery;9g-b coherent read capabilities
and bounded paging;9g-c the actual owner/admin host screens and browser proof.
New records must bind the exact displayed terms/source and preserve an original
unknown intent across policy changes. Do not silently upgrade old requests to
new document/content fields, and do not let a compatibility integer/old command
path bypass the required document/hash for a newly bound publication. Existing
immutable opaque historical facts remain unchanged and honestly labeled.

Domain/SQL values remain int; the API boundary normalizes valid decimal strings
before domain hashing so equivalent old valid integer clients retain original
idempotency semantics. Strict numeric syntax and MAX_MINOR checks are required.
No browser storage of secret details/auth/evidence payloads is permitted; a
server safe-result lookup must distinguish recorded, known absent and unknown
inflight conditions. The operator result path remains available to record real
observations during pause without authorizing new bank activity.

Do not edit frozen financial_payout_v1. Any new companion migration is a child
of the actual then-current head, coordinated before creation. Source ownership
and the next shared gate will be coordinated byroot; this checkpoint is not
acceptance of P01 UI or permission to publish actual contractual terms.

### Stage9g-a implementation clarifications

The separate P01 history-authority finding is now fixed and independently
rechecked. Root's new shared makefix is running;9g source remains frozen until
that checkpoint completes. After release,9g-a owns only API money presentation,
readable publication/acceptance, own safe recovery and masked requisites. Context/
capabilities/paging belong to9g-b, actual owner/admin screens to9g-c.

Preserve pre9g immutable command replay hashes: adding optional document/schema
fields to command DTOs must not append null/default keys to the canonical payload
of an old retained command. Normalize accepted integer/string money before domain
hashing. A legacy same-key replay may return its original safe receipt; a new
command cannot use compatibility to accept an opaque or unseen document. Public
responses serialize all monetary fields as canonical decimal strings even when
the stored original receipt used integers; stored history/hashes are unchanged.
Test old retained integer command→new equivalent string replay explicitly.

Enabled new publications need a real immutable readable document and exact field
definitions. A disabling publication may retain an existing actual document or
have no readable companion; absence is explicit and permits no new acceptance.
Emergency suspension must not require inventing legal text. Old opaque enabled
publications and a missing companion schema are unavailable for new requisites
acceptance; current history/status remain readable. Update positive runtime/API
fixtures to publish actual visibly synthetic full documents at the new revision;
keep old-revision/populated-migration compatibility tests meaningful instead of
weakening this gate. Never rewrite frozen payout_v1 or old terms/receipts.

Operation status is own-only, with the same actual actor command barrier and a
fresh post-wait lookup. It need not use the separate context endpoint's strict
read-only snapshot mode: taking the existing User barrier under READ COMMITTED is
allowed, without inserting a receipt/wallet or mutating state. A response that no
receipt is recorded is an observation at that barrier, not proof that a delayed
HTTP request can never arrive. Network uncertainty stays unknown, reserve retry
keeps the same exact key/payload, and no absent lookup justifies a new money key.
Whitelist safe owner results for requisites/request only; administrative command
secrets, protected legal/evidence history, input hashes and plaintext details are
never exposed by this recovery route, including after admin authority is lost.

Masked own requisites remain readable during pause/key loss, but server-derived
usable must be false when current document/requirements/key prerequisites do not
hold. No plaintext decrypt/reveal endpoint is added for owners. Distinguish this
safe recovery from a guarantee that a later reserve will pass current money
guards. Run actual signed TG/MAX API, bigint/signed amount/strict grammar, legacy
replay, unreadable terms, migration retention and unknown-response recovery RED→
GREEN before expanding to9g-b. Full integration/review remain root-owned.
