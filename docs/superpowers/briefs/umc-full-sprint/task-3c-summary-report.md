# Task3c — own campaign summary read/UI checkpoint

This implements the real summary destination needed before weekly digest sends.
R02/AC29 remain partial: weekly delivery and old scheduler cutover are not yet
implemented by this checkpoint. No notification was sent or flag enabled.

## Implemented source and scope

- New CampaignSummaryService and SQL adapter run one read-only repeatable
  snapshot. The client needs the actual advertiser role and own order; an actual
  current manager sees only their current assignments. Removed membership,
  foreign scope and blocked actor fail explicitly. Reads create no wallet.
- Financial positions expose exclusive current work-state counts. Current work
  projection must match the latest immutable event and actual current assignment
  scope; an inconsistent projection is unknown. No saved work record is shown as
  not_configured, not inferred success. Contact acceptance is counted separately
  from actual immutable delivery/interest/applied outcome sources.
- Legacy interactions remain distinctly labeled feedback, scoped to the actual
  advertiser and deduplicated by creator/latest observation. A manager's view
  also intersects their actual accepted in-offer dispatch assignment. A positive
  legacy feedback flag is never described as v1 publication/payment evidence.
- Signed POST /miniapp/api/orders/{order_id}/campaign-summary is mounted in the
  actual factory/router for both hosts, rejecting caller actor/outcome/query
  fields. Missing schema/service/role/source has an explicit safe error.
- Both production templates have the UMC summary screen and local controller,
  actual client/manager order-list entries, strict ?summary=UUID deep link,
  five locales, native back/main controls and safe DOM. Loading/empty/error
  hides obsolete counts. Late requests cannot overwrite a different open view.

## Verification and boundaries

Initial missing module and screen were observed RED. The actual PostgreSQL
suite then covered current membership, immutable result consistency, provider
acceptance distinct from work success, a30-creator legacy aggregate, source
unavailability, both actual signed platforms, core-off read and a concurrent
work transition without a fractured snapshot.

Last scoped backend gate:12passed,99.21% of127 statements across SQL adapter,
service and API;98% floor unchanged, sysmon tracer. Last own browser gate:
18passed covering five locales/both hosts, actual order entry/native back,
legacy source distinction, refresh failure, invalid deep link, empty/unknown,
320px/dark. RU light Telegram/MAX and KK dark320 screenshots inspected. Ruff,
focused mypy4source modules, Node parsing and git diff whitespace checks pass.
Logs: /tmp/umc-summary-verified.log and /tmp/umc-summary-browser-verified.log.

Synthetic data is only at the provider/browser boundary; no live WebView,
notification, payment, legal decision or global new-wave gate is claimed.
Independent fresh review is still due. Weekly committed-attempt delivery,
one-per-week deduplication and production replacement of per-author feedback
reminders remain Task3d, with actual30-author scheduler/runtime proof required.

## Independent review and source-loss follow-up

The omitted financial_collaborations and paid_selection_delivery_outcomes
relations were reproduced RED, then added to required-source preflight. Both
direct-service and actual signed API tests now cover all five required source
relations:20passed,99.21%127 statements. The fresh Task10a/3c reviewer rechecked
all three findings after fixes:95backend/48browser passed plus signed-API probes;
all findings resolved, these two narrow slices scope-ready subject to root's
integration gate. Report /tmp/umc-full-sprint-reports/task-10a-3c-independent-review.md.
Task3d weekly implementation is now separately tested60cases/99.63% and under
its own independent review; it was not approved by this summary review.
