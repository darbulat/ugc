# Task3d — weekly campaign digest and scheduler cutover

Status: implementation and focused validation complete enough for independent
review; final explicit-floor rerun has passed:61 checks,99.63% of271 behavioral statements. No full-tree gate,
production activation, live send, commit, native-device proof or whole R02/product
acceptance is claimed. Task3c own summary screen/API was independently rechecked
with Task10a; all three findings there are resolved.

## Current implementation

New CampaignDigestService uses dedicated campaign_digest_requests/jobs/attempts/
outcomes. Requests, detached attempts, start markers and transport/recovery
observations are immutable in PostgreSQL. A job is only a mutable projection.
The request is unique per order/current recipient/UTC Monday week; a second
request also requires at least seven elapsed days since the prior request,
including failed/unknown/obsolete requests. Thus a calendar boundary cannot
produce two reminders a few hours apart. A next-week summary is a fresh
informational snapshot; unknown older sends are never automatically retried.

Discovery considers actual captured, allocated financial selection items (not
quotes), or real due pending legacy interactions, excluding deleted orders.
It selects the actual client with its existing advertiser role and current
managers with actual positions in that order. Recipient must be active and have
a current positive private native address. Clients see whole-order counts;
managers only their current positions. Creators do not receive a per-author
rating cascade. Financial contact acceptance, actual work state and legacy
feedback remain distinct; absence of a response creates no work success or
financial movement. Text exposes aggregate counts only, plus an own-order
summary link, in five locales. Details are read through the existing signed
Task3c screen on both host shells.

The write protocol takes sorted client/recipient User FOR SHARE rows, existing
order advisory/row barriers, current advertiser/manager role rows, shared identity
history, ordered item and legacy interaction/dispatch barriers, then the delivery
job. It re-reads current scope/contact/source. Request source and prepared source
are retained separately; preparation can take a newer factual snapshot. Immediately
before I/O the exact stored attempt and source fingerprint are revalidated and
an immutable start marker commits. The transport runs without a DB connection.
Only the matching unexpired job can apply an accepted observation. Changed scope,
late response, failed, unknown and crash recovery retain their actual facts and
cannot trigger an uncontrolled retry. A reused channel/provider reference is
retained unapplied, serialized by a receipt-specific advisory lock and guarded
by a partial unique applied-receipt index. No delivery result proves a read,
agreement, publication or commission entitlement.

Migration campaign_digest_v1 follows the coordinated frozen checkout_v1, after
financial_payout_v1 and campaign_foundation_v1. It is registered in Base metadata.
Downgrade locks all four tables and refuses populated history. Current schema is
frozen for the independent review. No existing money schema is rewritten.

CAMPAIGN_DIGEST_ENABLED is false by default and additionally requires the existing
FEEDBACK_ENABLED. Disabled factory/runtime constructs no transport/session.
Combined scheduler and standalone feedback scheduler now call the dedicated
weekly runtime; neither production entry point calls the retired per-interaction
rating loop. Legacy explicit-feedback helper functions/history remain available.
The payment/new-order outbox and actual collaboration critical-notice workers
remain independently wired; financial core or payout flags do not turn digest
sends on. No environment flag was activated.

## Current evidence and boundaries

Initial missing-service collection RED was observed before implementation.
Meaningful PostgreSQL RED then exposed deleted-order sends, and a separate RED
exposed reuse of one provider receipt for two applied sends; both were fixed.
Two fixture-only errors were corrected (capture-time clock ordering and duplicate
advertiser setup); they are not product fixes. A temporary wrong item attribute
in a newly added discovery condition was caught and corrected to selection_state.

Final focused result:61 passed (21 PostgreSQL,12 scheduler and28 native
payload/URL/factory cases),99.63% of271 behavioral statements with the explicit
unchanged --cov-fail-under=98. Service, scheduler and factory100%; only the
fail-closed owner-change-after-initial-read guard remains unexecuted. Log
/tmp/umc-digest-reviewed.log; coverage /tmp/umc-digest-reviewed.coverage. Separate runtime/legacy regression set: 72 passed, including
all existing feedback helper tests, orchestration cancellation/resource cleanup,
new gate and native payload tests. Ruff and mypy for the six new Python source
modules pass. The61-case explicit-floor run was completed independently of the72-case carry run; counts overlap and do not represent a full-tree gate.

PostgreSQL discovery scenarios each use a fresh owned synthetic UUID schema, so
global source scans are not hidden behind test-only order filters. Tests include
30 creators through actual Container/factory/scheduler, no 24h/72h/7d cascade,
actual financial capture and manager subset, scope/contact deletion after prepare,
failed/unknown/wrong-channel receipt, concurrent workers and delivery calls,
rollback, immutable history, crash and late acceptance, seven-day cadence and
provider-reference reuse. No live provider credentials or external sends are used.

Full R02 acceptance still requires root integration checks and independent Task3d
review. Batch status editing remains explicitly deferred by canonical amendment.

## Independent review and late-receipt follow-up

The fresh independent Task3d review found one P2 provenance gap: an accepted but
unapplied old receipt was not considered used. Actual PostgreSQL reproduced
late-first acceptance followed by the same reference on another weekly request.
Root added a parametrized regression (RED1fail1pass), then changed the same
advisory-serialized lookup to claim every earlier accepted transport observation,
regardless of applied. Later repeated observations remain immutable/unapplied.
No schema change was needed. Three affected PG cases passed; the reviewer's
independent reversed original probe also passed with chronological applied
[False,False]. The updated independent report marks this narrow scope ready,
with no unresolved concrete findings; it does not approve the whole branch.

After the fix, the complete explicit98floor focused run passed61cases/99.63%
271behavioralstatements; service/scheduler/factory100%, one fail-closed guarded
concurrent-owner-change return unexecuted. Scoped Ruff/mypy and whitespace pass.
The separate pre-fix independent full selected run passed68cases, and the
post-fix independent rerun/probe are recorded separately, not added as unique
acceptance counts. Report /tmp/umc-full-sprint-reports/task-3d-independent-review.md.
A concurrent test-schema migration catalog introspection failure occurred before
one independent probe; a sequential retry passed, and no production or legacy
migration was changed for that fixture timing issue.
