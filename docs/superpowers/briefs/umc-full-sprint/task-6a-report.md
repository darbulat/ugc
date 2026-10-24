# Task6a — actual paid selection interest and own-client read checkpoint

Worktree: `/home/bulat/.codex/worktrees/umc-full-sprint/ugc`.
This is a partial integration checkpoint, not final acceptance of R01/R05/O01.

## Implemented

- The actual `OfferResponseService` factory routes versioned financial orders
  through `PaidSelectionInterestService`. Legacy orders retain their existing
  path; a missing/disabled versioned runtime cannot fall into legacy writes.
- Confirmation reloads current actor/status, advertiser role, confirmed unique
  Instagram, actual capture/intent/allocations/policy and purchased positions.
  Sorted User barriers precede order/payment/manager coordination, shared
  identity history, then item locks. New manager discovery restarts the whole
  transaction before creating an assignment or job.
- One immutable interest per order/creator and order/verified Instagram;
  one initial assignment and durable delivery job per accepted interest.
  Overflow is an actual waitlist interest without a paid position/job.
  Assignment does not invent a publication brief, due date or work success.
- Managers are selected only for positions with purchased accompaniment.
  The advertiser role is protected through commit by a PostgreSQL KEY SHARE
  lock before the shared history barrier; concurrent role deletion cannot
  consume a position after the role disappears.
  Counting accepted positions uses the immutable financial interest source;
  unanswered legacy dispatch rows do not consume the purchased pool.
- Telegram/MAX confirmations preserve acknowledgement/product links and skip
  the old untracked contact sender for this flow. Five-locale acknowledgement
  says interest is saved and does not claim the client already received it.
  Paid-selection failures use their own localized error path: a temporary
  refusal keeps the offer button and does not falsely close the order.
- Signed own-client `POST /miniapp/api/financial/orders/{order_id}/selection`
  is mounted in the actual application. It exposes stored component prices,
  current assignment/delivery state and separate immutable accepted history.
  A prior creator's acceptance never labels the replacement as delivered.
  Provider references/private evidence are not exposed.
- Reads use their own `REPEATABLE READ READ ONLY` snapshot with no wallet
  creation. Own history remains readable with `writes_paused` when core is off.
  Missing current role, foreign scope, absent migration or unsupported legacy
  order fails explicitly. A mutable accepted/refunded projection alone is not
  represented as an authoritative delivery/refund fact.

## Evidence

`tests/postgres_financial/test_paid_selection_interest.py` and
`test_selection_view_api.py` cover real capture, actual production factories,
duplicate/concurrent confirmation, purchased pool/waitlist, historical IG
reuse, actual manager discovery race, rollback, both signed platforms, rebuilt
containers, current role revocation, missing schema, snapshot consistency,
actual provider acceptance and replacement history. Native-routing and
unavailable-capability tests cover the boundary to the prior bot flow.

- First missing implementation and route produced RED, then GREEN.
- A separate RED proved stale pre-lock time could admit a late interest.
  The repository now reads the injected server clock after all scope locks;
  the same boundary test is GREEN.
- Fresh focused gate after independent-review fixes: **35 passed; 99.57% of233 statements** across six
  interest/read service, SQL adapter, API and bot-error mapping modules. The98% floor is unchanged.
  `COVERAGE_CORE=sysmon` avoids Python3.13 C-tracer attribution errors.
- Native/legacy affected tests: **122 passed**; initial financial factory/
  interest and legacy service compatibility selection: **36 passed**.
- Focused Ruff and Mypy with `--check-untyped-defs` pass.

Independent fresh review reproduced one Important role-deletion race and one
Minor misleading-error issue. Both were observed RED, fixed at their source
and verified GREEN. The reviewer reran nine targeted tests and reports Ready
for Task6a only, with no remaining findings; broader money paths were declined.
Report: `/tmp/umc-full-sprint-reports/task-6a-independent-review.md`.

The shared `make fix` checkpoint now passes:5280passed,1skipped;98.27%
global coverage with unchanged98% floor, actual PostgreSQL enabled and the
whole live E2E directory excluded. Format/Ruff/Mypy pass. The prior three
empty-result failures were reproduced at the100-event batch boundary and
fixed by test-only bounded target-event waiting, which rejects target errors
rather than retrying them silently. No production batch or financial rule
changed. Log: `/tmp/umc-full-make-fix-rerun.log`.

Accepted delivery itself belongs to Task6b's committed-attempt/one-shot worker,
not to a public outcome command. The read test consumes that actual worker
with a synthetic provider boundary; no live message was sent.

## Still open

Actual selection closure, agreed extensions, authoritative refunds/corrections,
the published refund-window anchor/deadline and client14-day maturity are not
implemented by this checkpoint. Neither `OrderStatus.CLOSED` nor this contact
acceptance is used to release client money. The30-paid/25-delivered/5-refunded
criterion, reserve replacements, payout/admin workflow and whole-branch gate
remain open. No commit, deployment or live financial operation was performed.
