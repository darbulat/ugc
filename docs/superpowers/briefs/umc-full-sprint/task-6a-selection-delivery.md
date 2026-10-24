# Task 6a — real selection delivery before client maturity

Worktree: `/home/bulat/.codex/worktrees/umc-full-sprint/ugc`.
Owner: root. The full20-task/30-AC goal remains active.

## Concrete gap and authoritative sources

The client consumer now creates payment-time pending obligations, but no trusted
producer yet proves that a paid selection position was actually delivered.
The document defines50000 minor RUB per unique confirmed interested creator,
with actual bot API acceptance of delivery to the client. Delivery is not read
receipt, author publication, manager success, or `OrderStatus.CLOSED`.

Existing `OfferResponseService.respond_and_finalize` serializes legacy interest,
round-robin manager selection and accepted/in_offer counts, then both Telegram
and MAX handlers call `_send_contact_immediately`. That generic messenger path
returns no reliable one-shot provider receipt. Its order-close count cannot
authorize a v1 client commission release.

## Intended implementation boundary

1. Add a v1-only interest coordinator behind the actual existing authenticated
   offer-confirm path. Preserve legacy behavior for orders without a financial
   version. Reload actual current creator role/status, verified Instagram,
   captured paid positions, interest and actual current manager assignments.
   One creator/order interest can allocate at most one paid position; overflow
   remains a waitlist response with no paid item/job/financial ground.
2. Discover all prospective client/creator/manager identities, then acquire
   sorted User barriers before order/manager coordination, shared profile
   history barrier, then item locks. Re-read under locks; a newly discovered
   identity requires a whole-transaction retry. Do not add User locks after
   order/history/item locks. Preserve payer/order lock order established by
   capture and monetary consumers.
3. In that same caller transaction, persist actual interest, initial versioned
   item assignment, stable delivery job and source provenance. Do not create
   an invented agreed publication brief/due date or collaboration success:
   selection due and author publication due are different facts.
4. Return an explicit v1 delivery-queued result so existing Telegram/MAX
   handlers do not also execute the old untracked client contact delivery.
   Keep truthful creator acknowledgement and useful existing order links.
5. New selection worker prepares/fences an immutable attempt and commits before
   provider I/O. Use the shared structural `ReceiptMessage` and actual one-shot
   Telegram/MAX adapters; never manufacture `NoticeAttempt` IDs. Send outside
   all database sessions/locks. Persist the actual provider reference or
   definite/unknown error in a new transaction after current-scope recheck.
   Unknown/crashed outcomes must not automatically resend. A delivery failure
   never loses the confirmed interest or pretends the paid position delivered.
6. An accepted delivery creates an immutable fact tied to the actual payment,
   selection allocation, paid item, assignment and creator. Uniqueness is per
   paid-position assignment and per unique creator/order. A later replacement
   cannot create another50000 paid position or duplicate client entitlement.
   Current item selection state is only a projection of those facts.
7. Expose a signed own-client selection status/list (and own assigned manager
   scope where appropriate). Provider outcome commands stay internal. A public
   body cannot assert delivery, timestamps, actor, amount or provider receipt.

## Deliberate next dependency

Client selection closure/maturity follows this stage. It must load actual
accepted deliveries, actual authoritative refunds/extensions, the immutable
published refund window and an explicit closure fact, then apply the separate
14-day hold. Never infer this source from existing author success schedules,
legacy order-close count or a caller-supplied available_at. The30-paid,
25-delivered,5-refunded acceptance case remains open until the real correction
and maturity producers run together.

Migration for selection facts/jobs will follow `accompaniment_leads_v1` (S01
agent owns that parent). New funding/selection tables belong to root; shared
financial ledger actor provenance is owned by the Task5d agent until handoff.

## Required evidence, starting with RED

- Actual signed creator interest -> real assignment/job -> actual production
  delivery worker with synthetic provider boundary -> immutable accepted fact.
- Duplicate clicks and two real PostgreSQL sessions cannot allocate two paid
  positions or exceed the purchased pool. Distinct confirmed creators only.
- Failed/unknown provider response, commit failure, stale assignment/contact,
  missing current verification and foreign actor never count as delivery.
- An interested but undelivered creator cannot mature client commission.
- Rebuilt container sees the same facts; default-off gates stay off; no live
  messages or financial-provider calls in this implementation session.
- Legacy offer-response/contact tests remain meaningful and green. Add the
  later30-author full journey; do not replace it with arithmetic or seeded
  financial balances.
