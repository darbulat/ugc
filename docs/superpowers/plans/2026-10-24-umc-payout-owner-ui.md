# UMC payout owner screens implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution. Steps use checkbox tracking. Root releases source ownership separately; PostgreSQL access is not part of this browser task.

**Goal:** Let an existing Telegram/MAX account read its real payout context, accept the actual published document, save encrypted requisites and explicitly reserve an exact amount, with safe recovery after a lost response.

**Architecture:** Add an owner controller to both existing templates using the signed app bridge, current9gb read DTOs and9ga commands/recovery. Separate exact-string money and bounded nonsensitive pending-intent persistence from DOM rendering. Follow the supplied UMC design system and existing native control adapter.

**Tech Stack:** Existing plain JavaScript/CSS/HTML, local UMC tokens/fonts/logo, Telegram/MAX bridge, Playwright against actual production assets and synthetic API boundaries.

**Spec:** `docs/superpowers/briefs/umc-full-sprint/task-9g-payout-ui.md` (root-approved stages9ga/b/c); actual `miniapp/payout_api.py`, `payout_view_api.py`, `application/services/payout_view_service.py`; archive provenance in `miniapp/design-system/PROVENANCE.md`.

## Global constraints

- This is9gc-1 owner UI. Administrative publication, queue, protected history/reveal and bank-result forms belong to the next separately reviewable9gc-2. Do not render a nonfunctional admin action or claim all P01 is complete.
- No backend/migration/financial formula/configuration changes, real legal text, provider call, transfer, notification, flag activation, commit or deployment.
- Both actual templates use the same controller. All calls go through `window.__umcAppBridge.request`; no stored/copied initData, caller owner selector or direct SDK payment API.
- Every monetary wire value remains a canonical decimal string. Never use Number/parseFloat, floating arithmetic or Number-based Intl for amounts. Maximum is9223372036854775807 minor RUB; no smaller invented product maximum or rounding.
- All owner secret details stay in memory, never storage, URL, data attributes, logs, console, clipboard or exports. Clear forms and their objects after submit completion, back/close, account change and pagehide. Do not restore them from an unknown request.
- Reserve intent is persisted before I/O, partitioned by actual server actor UUID and platform, with only schema version, action, operation key, requisites UUID, canonical amount and RUB. Requisites-save recovery stores only its operation key and nonsensitive displayed document context. No automatic mutation or retry on mount, event, timer, status result or focus.
- Never discard an unknown reserve or replace its key/payload because policy/balance/status changed, time elapsed or a receipt lookup says absent. Only explicit exact-key retry is allowed. Original receipts are distinct from refreshed current status.
- User-facing chrome/errors/states/actions have complete RU/EN/KK/BE/UZ variants and RU fallback for unknown locale. Display legal text in its actual source language, as plain text with preserved paragraphs/hash/version.
- Use existing mint section/cards/type scale, host theme/safe-area/keyboard behavior and `UMCShell.syncControls()`. No new design language, external assets, fonts or dependencies.

## Review focus

1. Store commits but its response is lost: recover the safe result by key without retaining/resubmitting plaintext or creating a replacement key automatically.
2. Reserve commits but its response is lost, then requirements change: retain the exact original intent and distinguish receipt recovery from fresh request authority.
3. Account/platform or active screen changes while a read/mutation completes: never render another account's data, resurrect secret forms or send an inactive native action.
4. Source mismatch, missing wallet/key/publication, storage failure or missing BigInt: show honest readable state and disable only unavailable new actions before I/O.
5. Maximum,2**53 boundaries, malicious document/mask text and320px layout: preserve exact money, plain-text display and usable visible/native controls in both hosts.

## Files and source ownership

Create `miniapp/umc-payout-money.js`, `umc-payout-state.js`, `umc-payouts.js`,
`umc-payouts.css`. Modify both `app.html` and `max_app.html` only for stylesheet,
ordered deferred scripts and one empty `screen-payouts` mint mount. The controller
adds a visible `data-payouts-open` entry beside the partner heading, outside its
data-dependent hidden content. Narrowly change `umc-partner.js::busy` so its
blanket button disable excludes that independent payout navigation control,
including while a partner read remains unresolved. No partner service rewrite.
The two inline bridges also gain the request-context and screen-change hooks
specified below, preserving existing `request`/`showScreen` callers unchanged.

Add `tests/e2e/test_miniapp_payout_owner_ui.py` and narrowly scoped static asset
tests beside existing Mini App asset tests. New tests use actual templates/assets
with intercepted signed bridge requests. Existing browser suites remain carried.

## Task1: Exact amount and bounded recovery state

- [ ] Write failing browser/Node cases for decimal comma/dot inputs, positive0.01,2**53±1, maximum `.07`, overflowing `.08`, signs, exponents, whitespace, leading zeroes, three decimals, non-ASCII digits and missing BigInt. Pin exact money display without numerical conversion.
- [ ] Implement string splitting/padding, positive/max validation and direct string formatting. Use secure random operation keys; missing required key-generation capability disables new actions rather than using weak fallback.
- [ ] Add failing storage cases before implementation: wrong actor/platform, extra/secret fields, malformed IDs/key/amount/schema, unavailable read/write, reload, unknown store and unknown reserve. Validate stored objects by exact allowlist; treat them as navigation/recovery data, never server authority. Persist before initiating any mutation; storage failure prevents the send.
- [ ] Implement namespaced storage and memory cleanup. Retain unknown intent across reload without a timer/TTL. A malformed record or unsafe storage state blocks a new intent with localized guidance; do not silently erase a possibly unresolved operation. Status recovery reads move no money.
- [ ] Capture the immutable platform/actor partition and operation key/action/payload for every asynchronous operation. A completion may clear or update a stored record only if its current exact allowlisted value still equals that captured record. An old response for request A cannot remove or rewrite a newly persisted request B on the same account/screen. Do not dynamically recompute its storage key from current UI state. Before accepting operation recovery, require the expected server action and the safe receipt's matching amount/currency/requisites for a pending reserve; otherwise retain uncertainty.
- [ ] Run the complete focused pure/browser helper tests, then node syntax checks. Record actual RED/GREEN evidence; no PG operation.

## Task2: Reachable owner reads, terms and encrypted requisites

- [ ] Add failing actual-template TG/MAX tests for partner entry even when partner data fails, signed payout context, known-empty versus unavailable money, bounded own/masked pages, safe request detail, pause/key loss and auth/role errors. Deep-link navigation is a hint only; assignment/selection routing keeps precedence and server scope remains authoritative.
- [ ] Add the common mounts/assets/controller. Initial reads use `/payouts/read/context`, `/own`, `/masked` and `/{request_id}/detail` with bounded keyset tokens. Each response is independently fresh; avoid implying cross-request snapshot consistency. Derive actor partition only from the current context, never `_me` or stored owner ID.
- [ ] Add a narrow opaque request context to both existing bridges: the bridge privately captures the current host auth/platform for the initial payout context, exposes only `request`/`isCurrent`/`dispose` behavior, and compares fresh host auth/platform synchronously before each bound request. It injects that same checked fresh auth into the outgoing body rather than reading it again later. The controller never receives/stores the auth value. Observing a changed context permanently invalidates it, clears private forms and requires a fresh payout context before a new decision. Existing unbound bridge callers are unchanged.
- [ ] The bound bridge cannot accept body overrides for `init_data` or `platform`: outgoing authentication always comes from its checked private context. Pin this with the actual bridge; no controller-owned auth copy or authentication-bearing event is added.
- [ ] Emit a nonsecret screen-change event from the existing `showScreen` after the actual transition; use it plus pagehide/visibility/focus and checks before every request/completion to clear abandoned private forms and invalidate stale UI generations. A local counter alone is insufficient because another controller or the host can switch account/screen. Pin account switch immediately before store/reserve, switch during pending reads, return to the prior account after observed invalidation, and departure through another controller. No old-context request may be sent under the new host identity.
- [ ] Render current requirements/full document/schema using safe DOM text, exact source locale/hash/version and an unchecked accessible acceptance control. Render only actual published fields and permitted values; text otherwise. Never invent legal-status choices or turn an opaque reference into a document/link.
- [ ] On explicit save, persist a safe recovery record, send displayed requirements/reference/document ID/hash/accepted=true with details in memory, then clear secret controls/objects. Recover only safe masked store result by operation key after unknown response/reload. Do not resubmit details automatically.
- [ ] A recovered store result must have action exactly `StorePayoutRequisites`, a valid nonzero requisites UUID and requirements ID/document ID/document hash exactly equal to the captured displayed store context. Missing or mismatched context stays unresolved and cannot clear that pending record or start a replacement key automatically. Accept only the explicit safe masked receipt fields; never infer document acceptance from the current publication or another saved mask.
- [ ] Keep a usable saved mask selectable without returning plaintext; refresh context when requirements change. Mask usability is distinct from amount-specific reserve permission.
- [ ] Bind new-flow entry to current `capabilities.begin_request`, secret save to `store_requisites`, and history availability to `read_own_requests`; do not derive them from a single paused flag. Pin begin=false/store=true, store=false/history-readable and usable-mask/preview=false independently. Use an explicit owner DTO allowlist even when the current actor is admin; never render/fetch protected execution, actions, latest-publication or history in this owner-only phase.
- [ ] For9gc-1, support only an unambiguous single `view=payouts` list entry after the existing app-ready/authentication bootstrap. Do not add a missing-country exemption or change registration. Yield to any assignment/assignment_id/selection selector, reject duplicate/conflicting view selectors, and test against the actual existing listeners. Arbitrary request-UUID deep links are deferred; detail IDs come from own-page rows or a validated own operation receipt. This avoids using an admin-capable detail endpoint as an unscoped owner selector.
- [ ] Run complete owner read/terms/requisites/recovery tests and actual ASGI static GET byte checks for both hosts. Synthetic data only; no live bot lifespan.

## Task3: Explicit reserve, authoritative status and uncertain response

- [ ] Add failing owner journeys: exact amount→`/reserve-preview`→review→distinct reserve click; duplicate/native clicks; stale preview; insufficient amount/dispute/debt; request commit then lost reply/reload; absent receipt; old recorded receipt plus newer current paid/blocked status; policy change while unknown; storage failure before I/O.
- [ ] Display exact amount, masked destination, actual accepted document context and reservation/original72-hour explanation. Preview is a server hint; final command reauthorizes. Enable final action only after the current explicit review; no lower balance or UI state infers payment success.
- [ ] Tag each preview with its captured actor/platform, selected requisites, exact amount/currency and review generation, because the response echoes only amount/currency. Only a matching `can_reserve:true` response can enable that new final action. Amount/requisite edits, context/requirements changes or leaving review invalidate the confirmation. A late preview cannot enable another tuple. No invented preview TTL or lock guarantee; unknown exact-key retries follow their original recovery contract instead of becoming new preview-gated commands.
- [ ] Persist the exact nonsensitive reserve command before I/O. Keep key/payload immutable while unknown. Explicit retry sends exactly that payload/key, without silently selecting new requirements/requisites/amount. Automatic operation-status reads may recover a safe original receipt; refresh current detail separately before another new decision.
- [ ] Present reserved/approved/executing as processing; paid only from authoritative current server state. Preserve unknown/failed and missing-source states without offering a second bank transfer or fabricated cancellation. An explicit new request may start only after the prior intent is conclusively reconciled; no new key from absence alone.
- [ ] Ensure async completions check the current account/screen generation. Back/pagehide clear secret forms immediately, preserve only allowed pending records and never recreate a closed form from a late response.
- [ ] Also pin delayed operation-status/store/reserve responses for A arriving after an explicit reconciled New Request B exists in the same screen. Cleanup uses the captured partition and exact compare-before-remove rule, and receipt/action mismatch never clears B or authorizes a new key.
- [ ] Run all complete focused owner journeys, node syntax and carried partner/selection/checkout/linking/browser design cases. No backend acceptance is inferred from browser interception.

## Task4: Five locales, native controls and visual review

- [ ] Pin visible label/help/error association, polite state/error regions, heading/error focus, duplicate-submit busy state and one visible final action. Native MainButton mirrors that actual visible button through the existing adapter; inactive forms cannot submit. Native Back follows the actual prior screen and cleanup rules. Browser buttons remain functional without SDK support.
- [ ] Complete all five copy dictionaries and safe exact error-code mapping; unknown server errors use localized generic copy and retain uncertain intent. Never render raw exception/detail text as an error message. A409 refreshes context/status and requires a fresh explicit decision without automatic mutation.
- [ ] Exercise320px light/dark for every locale, both hosts, BigInt/storage failure, malicious document/mask text, theme and viewport/safe-area events. Inspect captured terms/review/unknown/status states without visible bank secrets.
- [ ] Verify exact served asset bytes in both production ASGI apps without lifespan/network, run relevant browser carry, and report exact commands/counts/screenshots. Root owns independent review and the later shared makefix. Do not aggregate overlapping test sets or label mocked host proof as real device QA.

## Handoff boundary

The9gb SQL/source gate and9h financial-current-identity fixes are separately
owned and remain mandatory backend checks. This plan authorizes neither those
edits nor payout activation.9gc-2 admin workflow,6c corrections, actual bank/legal
facts, real device QA and full20-task/30-AC acceptance remain open after this
bounded owner screen implementation.
