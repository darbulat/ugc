# Task6c — correction cases, refunds, replacement and debt

Status: root implementation design, revised after independent design review on
2026-10-24; no new correction code or money claimed.
Independent follow-up found bounded6c-a1 scope-design-ready; its explicit proof
cutover clarification is included below. This is design readiness only, not
implementation verification or acceptance of the wider6c-a/b/c.
This follows actual paid-interest/delivery/work/P01 sources. It is not permission
to activate providers or invent refund timing, contractual offsets or bank facts.
Canonical financial-v1/R05, original20-task30-AC scope and Task6 plan apply.

## Existing authority and concrete gaps

Immutable capture/quote/allocation, initial paid item/assignment/interest and
accepted contact-delivery sources now exist. Work results have immutable events,
actual dispute sources and separate success14-day maturity. P01 is completing
available-only reserve/manual proof/reconciliation. JournalMovement and replay
already model reversal/debt/recovery with source/case references, but there is
no trusted v1 correction command, refund authority, case resolution, replacement
writer or repayment producer. FinancialLedgerService.transfer only permits
lifecycle transfers; do not widen it into a caller-supplied generic journal API.

Initial paid contact ACCEPTED is unique per item and assignment. A replacement
cannot insert a second initial paid delivery or rewrite that immutable receipt.
Existing Collaboration has no administrator dispute-resolution/cancellation
transition. Existing paid-assessment adapters need a trusted net-funding view;
changing selection_state alone must never become evidence of an actual refund.

## Stage6c-a: authoritative case/refund evidence and ledger compensation

- Add immutable authenticated command receipts, correction case events, original
  component refund intents, observations and applied correction records. Keep a
  separate replayable state projection; freeze full resulting state in each event
  and reject inconsistent projections. Migration follows the coordinated actual
  head, never a guessed parent; no currently frozen schema is modified.
- A participant can request review only for their actual current own scope, with
  a substantive reason and retained source/evidence. An actual current active
  administrator reviews the persisted request with operation key, expected version,
  reason and protected evidence reference. A user request or review decision is
  not a bank refund. No caller boolean can confirm work/payment or select a
  foreign beneficiary, allocation or arbitrary journal entry.
- Freeze original capture/payment/account, component allocation, paid item,
  original currency/minor amount and current assignment/source versions. Refund
  requested is distinct from actual observed refund. Initially a reviewed manual
  operator observation must explicitly say manual_admin_observation and retain
  its evidence; it must never say provider-verified. A real provider adapter waits
  for the selected actual provider/access. Unknown and unmatched facts remain
  durable/unapplied, including refund-before-capture ordering.
- Claim any observed successful physical bank/provider reference globally under
  one shared physical-proof authority for payout, refund and incoming repayment.
  Namespace it by actual configured source/provider, canonical account, physical
  direction and provider reference using unambiguous component encoding. A caller
  account label cannot create a new namespace. Claim at observation time, even
  when its first observation is unapplied; retain the original owner forever.
  A later different request cannot reuse that proof. Only exact same-intent proof
  resolution at a fresh current version may apply it. Preserve all observations;
  never release a reserve because of timeout, stale version or missing key.
- At the common-authority cutover, inspect immutable pre-existing P01 successful
  outcomes/settlements, including unapplied paid observations, as existing proof
  owners under the SAME unambiguous cross-producer mutex used for new claims.
  Both P01 and refund writers must use that authority. No fabricated historical
  claim rows or bank verification is needed. Only a recognized actual configured
  source/account maps to the trusted namespace; missing/unrecognized caller labels
  remain retained exceptions rather than new trusted namespaces. Historical
  conflicting ownership stays review-required, never arbitrarily reassigned.
- Distinguish immutable gross capture validation, live per-original-component
  net funding, and unresolved-observation blockers in one correction-aware
  funding/guard contract. Check the live contract before interest/assignment,
  delivery preparation and application after unlocked I/O, forward client/
  creator/manager issuance, maturity, reserve, review/start and settlement. Keep
  WorkFinancialGuard and legacy guards. Do not rely on selection_state or outbox
  timing. Historical gross assessment remains possible through the explicit
  atomic original-assessment/correction path below; this does not authorize new
  forward fulfillment or spendable earnings while the correction is unresolved.
- Before capture, correlate an observation only to its actual configured source/
  account, original payment reference and known order/invoice intent if present.
  Absent capture/allocation stays absent. Append a fresh reviewed match later;
  never rewrite the observation or fabricate IDs. Record a later real gross
  capture normally, keeping the related scope blocked until reconciliation.
  Insufficiently correlated observations stay in the exception queue and cannot
  silently block arbitrary or unrelated orders.
- Preserve original gross capture and payment-time snapshots. Compute net
  selection entitlement from cumulative applied refund facts. For percentage
  commissions, evaluate each original obligation with its frozen base, rate/
  override, recipient and currency: target cancellation is E(original_base) minus
  E(original_base minus cumulative_refund_base). Apply only the unrecorded
  economic delta, accounting for earlier source-linked replacement/cancellations.
  Source-entry links must belong to that same ground/component/currency. Freeze
  prior/new component totals and obligation breakdown in the applied fact.
  Each original component has cumulative refund capacity [0, captured allocation]
  across all cases/proofs. A physical amount matches one frozen allocation bundle
  only at its exact sum/currency; apply that bundle atomically or remain unapplied,
  never distribute an ambiguous amount or quietly apply a subset. Accompaniment never
  enters either referral percentage. Actual30paid/25delivered/5returned must
  reconcile to1250000minor selection base.
- Pending/hold/available corrections are linked immutable reversals to cancelled;
  available cannot become negative. Related reserved money stays blocked pending
  reconciliation and explicit reviewed payout handling. Historical paid never
  moves backwards: its correction creates a case-linked positive debt. Debt
  remains separate from available and cannot be silently netted from new earnings.
- Recovery requires a real incoming repayment observation against that debt,
  exact currency/amount/reference and actual recipient; a case decision alone is
  not repayment. Manager future offsets remain refused without the actual accepted
  agreement and reviewed applicable rule. No6% deduction or expiry is introduced.
- Before enabling positive reserved/paid corrections, implement allocation-aware
  resolution: unknown execution retains reserve; only reviewed verified nonpayment
  permits cancellation/release of the affected allocation. A real paid observation
  must settle the original allocation and create only affected correction debt
  together, preserving historical paid and unaffected allocations. Repeated proof
  cannot duplicate settlement/debt. Recovery must match actual original debtor,
  configured receiving account, currency, observation and case debt; excess stays
  unapplied. Ordinary P01 reject/result retry is not this resolution authority.
- Reuse common ordering: collect all prospective actors/old and new recipients,
  including reviewer, payer, old/new creators/managers, both historical referral
  sides and every existing ground recipient; sorted User and wallet barriers
  first, current role child-row barriers where required, then order/payment/history/item, then
  case/payout projections. Re-read scope after barriers; discover a new recipient
  late => refresh conflict, never take a late User lock. Reconcile before/after
  every monetary application in one caller-owned transaction. Persist actual
  bank observations despite expected application refusal using the P01 savepoint
  pattern. No external I/O inside a transaction.

## Stage6c-b: reviewed replacement of one existing paid position

Actual grounds: refusal, loss of contact or objective mismatch with the approved
brief. Retain the user request, source brief and substantive administrator
reason/evidence. Limit ordinary replacements to20% of the original purchased
pool (30positions =>6), serialized across the order; additional replacements
need a distinct reviewed exception. Counts come from immutable completed
replacement command commits, not later delivery success or mutable assignments.
Consume quota exactly once in the same transaction as old assignment closure,
old-ground cancellation and new same-item assignment; later failed/unknown contact
delivery does not restore quota. Freeze original purchased denominator and any
reviewed exception scope/count/reason. No replacement after actual
completed work/success_final/available. An unresolved success claim is not an
implicit failed work: review it explicitly first.

The new creator must have actual verified canonical identity and explicit current
acceptance tied to the correction case, paid item, proposed assignment and current
verified canonical identity. This is distinct from immutable initial interests;
never insert a second initial interest for the same creator. A manager/admin
cannot invent acceptance. Close the old
assignment version with its real cancellation reason/time and create the new
version on the SAME paid_item_id. Cancel the old pending author ground through
a linked correction before issuing a new one. No extra selection price or
second active author/management entitlement can arise. Use actual historical
payment-time attribution, including known absence within complete historical
coverage; unavailable coverage stays unresolved. A covered no-referrer result is
a durable no-recipient potential, never a zero journal entry. Never backdate a
new creator registration/binding or recompute old rates with a current grade.

Replacement contact delivery has a distinct immutable provenance path. The first
paid fulfillment remains historical; a replacement is not a second paid item or
base. Extend own selection/summary reads to show initial fulfillment and actual
replacement deliveries truthfully. Do not force a second insert through the
initial ACCEPTED unique-item constraint or describe API acceptance as publication.

Add a reviewed work resolution/cancellation command with expected Collaboration
version, actual claim/dispute evidence and explicit resulting state. Closing a
correction case alone cannot clear actual disputed work read by WorkFinancialGuard.
Recheck completed-work evidence under the same barriers before replacing it.

## Stage6c-c: actual own/admin UX and acceptance

Signed own participant request/view; current-admin protected review, refund
observation, replacement exception, case/repayment history. Private bank/evidence
is admin-only and reasoned reveals are audited. Screens use supplied UMC assets,
five locales, both hosts and native controls. Unknown, paused, disputed, partial,
reserved and paid-with-debt remain distinct; no optimistic refund/payment text.
Stable intent/key and current versions survive unknown requests without storing
plaintext requisites or authentication in browser persistence. Exact integer
transport follows task-9g-payout-ui.md: canonical decimal strings for EVERY money
wire field including nested history/observations/results; domain/SQL stay integers.
Show original receipts separately from freshly read state and never use JS Number.

Required actual PostgreSQL tests:30/25/5, refund-before-capture, pending/available/
reserved/paid corrections, two workers/admin repeats, reused applied/unapplied
proofs across recipients, full rollback, cumulative rounding, actual repayment,
source/projection corruption, old/new recipient and role changes, replacement
6/30 cap and reviewed7th exception, no replacement after completed work, same
paid item and no double author/manager commission. Add real signed API/browser
flows and independent review before accepting the whole R05/T01 slice.

## First implementation boundary: Stage6c-a1

Positive scope is full selection-component refunds for captured, unassigned,
undelivered positions after the actual agreed selection deadline. The authenticated
own client explicitly chooses refund instead of extension; a current active admin
reviews exact source/due versions. Amount comes from original captured allocation
(50000 minor per eligible position), never caller-selected ledger entries. A
reviewed manual observation, exact match and only pending client-referral
cancellation complete this slice. This unfulfilled-selection rule does not choose
the unanswered post-delivery refund-window anchor.

Persist immutable request/review/intent, manual_admin_observation, global proof
claim, match, application and command receipts with full resulting event state.
Validate replay/projection and current authority, derive all owners/sources server
side, reject changed-payload keys. Same-operation replay returns its original
receipt. Later rejection/case closure never negates an observed successful refund.

A missing original client assessment leaves the exact reviewed match pending
application. The delayed capture consumer may establish original gross pending
once and apply the eligible cancellation in that SAME caller transaction before
its successful consumption receipt. It must not mark correction applied without
its corresponding economic adjustment. A known no-referrer potential instead has
a durable zero-liability assessment, no invented recipient/zero journal. Coverage
unavailable cannot become zero liability. Original successful consumer receipts
remain immutable; later corrections append their own facts. Gross capture and
payment-time snapshots remain reloadable after refund projection changes.

Reconcile before/after, enforce cumulative capacity, link only actual pending
source obligations, and atomically commit journal/projection/application. Retain
observation/proof outside a bounded application savepoint on expected refusal;
outer transaction failure still rolls back everything. An early observation may
remain unmatched until real capture exists and a fresh same-intent review matches
it. No capture arrival auto-matches or auto-refunds it.

Assigned/delivered positions, partial component amounts, hold/available/reserved/
executing/unknown/paid, accompaniment, management and replacement remain unsupported
for positive application in a1: retain real evidence/case, block affected forward
scope, require later review, do not change paid/reserve/available/debt. Client
close/maturity, post-delivery refund eligibility, repayment application, arbitrary
positive adjustments, new UI and provider activation are excluded from a1. A
source-backed manual positive adjustment is a later separate reviewed producer,
never a generic raw-journal administrator command.

First RED matrix: actual30paid/25accepted-deliveries/5unassigned-refunds gives
1250000 net selection base; frozen10% client original150000 pending becomes125000
pending plus25000 cancelled. Do not assert client availability. Before/after
delayed assessment must agree, with known-no-referrer distinct from unavailable
coverage. Cover early observation then capture/current guard/fresh matching;
concurrent repeats and distinct-proof capacity exhaustion; changed payload,
foreign/stale/revoked authority; cross-payout/refund proof reuse with first result
unapplied; corrupt projection/forced savepoint and outer rollback; unsupported
assigned/reserved/paid/management scopes retaining facts while blocking new money.
New companion migration follows the actual coordinated head; frozen schema and
historical migrations remain unchanged. Independent review and the unchanged98%
floor are required before widening this boundary.

## Open business/external boundaries, not defaulted

The canonical source specifies a refund duration but not its anchor. Root has
already asked which event starts it; no answer is inferred from elapsed time.
Client close/refund-window maturity remains blocked on that actual definition.

The source permits accompaniment refund for unperformed volume under fixed
terms; it does not define arbitrary within-author partial-refund arithmetic for
a fixed600manager reward. Do not invent a proportional600formula. Apply only
actual explicit approved contractual scope/volume and source-backed review;
retain unsupported observations unapplied until their applicable rule exists.

Provider credentials, actual bank evidence, legal/accountant decisions and pilot
facts are still external. Synthetic fixtures never fulfill those requirements.
This design does not mark any20-task/30-AC requirement complete.
