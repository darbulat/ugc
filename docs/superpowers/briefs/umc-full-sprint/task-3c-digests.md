# Task3c — R02 campaign summaries and legacy reminder cutover

Design checkpoint, no implementation claimed. Canonical R02 plus its final
amendment remove per-author24h/72h/7d rating cascades, retain payment/new-order/
critical deadlines and one opposite-party success-claim notice. Batch editing
is explicitly postponed. A weekly summary must not infer work success.

## Current source and concrete gap

`feedback_scheduler.run_once` fetches individual due interactions, batch-loads
orders/users and calls `_send_feedback_requests_with_preloaded` for each. That
function can send to both advertiser and creator, then schedules another
per-interaction reminder. It currently has no financial-version exclusion.
New paid-interest routing bypasses the old contact sender, so ordinary new
selections do not create that legacy interaction; imported/stale interactions
can nevertheless reach this path. Merely failing new financial commands does
not replace the reminder loop with a summary.

The existing R04 notice worker has separate immutable requests/attempts/outcomes
and native card links. It must remain the owner of critical claim notices;
a weekly informational digest cannot start or extend72h or release money.

## Proposed slice and authority

Replace scheduled rating reminders with one durable weekly order summary for
the current client and each current assigned manager with work on that order.
Creators receive the existing critical collaboration notices, not one generic
rating reminder per campaign position. For a manager, counts include only their
current assigned positions. No creator/manager contact list or foreign network
is exposed. Both legacy and financial orders need truthful source-specific
counts and links; a legacy interaction is never interpreted as new paid-item
success. The source supplies weekly cadence; use an explicit UTC week key and
state that boundary in technical documentation. Additionally require at least
seven elapsed days since the previous request for that same order/recipient,
so a Sunday/Monday boundary cannot produce two summaries within a few hours.
Failed/unknown/obsolete requests also consume that seven-day cadence. A new
weekly snapshot is a new informational message, never a retry of an ambiguous
older send. This is a notification cadence, not a financial refund anchor.

The legacy feedback handlers can continue to process explicit user responses;
this cutover removes recurring scheduler sends, not original history or real
critical/payment/new-order events. Existing absent-order results must fail
honestly rather than sending from an invented order. New-order/payment delivery
must not be routed through the digest queue.

## Delivery and read requirements

- Persist a unique order/recipient/week request and exact factual source
  snapshot before any send; store current participant and source versions.
- A dedicated bounded worker commits immutable prepared attempt/start before
  one-shot ReceiptMessage transport I/O. No transaction/connection across I/O.
  Outcomes accepted/failed/unknown remain distinct; unknown/crash never auto-
  resend. An outcome is not read, agreement or success.
- Recheck current recipient status, exact current role/ownership and stored
  contact under the common User→history→order/items order. No private state in
  text. Lost scope skips a queued summary without erasing its request/history.
- Financial summary links to a real own-order selection/work page; manager
  links to their actual own assignments. Add missing legacy summary/status
  screen if needed before sending a launch link; no inert buttons.
- Weekly request uniqueness survives restarts and two workers. Failed or
  unknown delivery cannot produce a second uncontrolled weekly request.
- Read APIs use signed current own scope, a coherent read-only snapshot and
  actual source-specific status counts. Missing/unavailable differs from zero.
  Five locales, themes and both existing host shells remain required.
- Configuration must prevent construction/sends when paused, while reads and
  critical notices retain their existing independent behavior. No live sends
  or flag activation during implementation/tests.

## Evidence required before acceptance

A real PostgreSQL30-creator order must exercise actual scheduler/factory/worker
with recording external transport: repeated24h/72h/7d scheduler sweeps produce
no per-author rating cascade, at most one weekly aggregate per entitled client/
manager, while actual payment/new-order/claim-critical messages still use
independent durable paths. Include silence/no-success, rollback, two-worker,
role/contact change, failed/unknown/crash and next-week tests. UI/API/source
counts must reconcile, with no fabricated publication/rating/metrics.

A focused review must settle concrete legacy-summary link and source semantics
before production changes. Migrations must follow the coordinated current head;
no migration or source edits are allowed during the current shared gate.
