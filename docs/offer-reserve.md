# Offer reserve intake

Filling the last primary position starts one stored 72-hour reserve window.
Legacy orders use their primary `in_offer` positions; financial orders use
current item assignments. The deadline is independent of financial maturity,
selection delivery deadlines, refunds and collaboration completion. Filling a
replacement or receiving another response does not extend it.

During this window late responses and proposed prices are reserve candidates.
They do not automatically replace selected creators or change an agreed price.
Existing allocation, replacement and explicit customer delivery commands keep
their current responsibilities. New mass dispatch stops when the reserve
deadline is first set.

At `now >= offer_reserve_until`, all new response writes are rejected, including
prices entered into an already-open form. Native Telegram and MAX callbacks
also check intake before offering actions. Cards read after expiry show
“Набор завершён” without response buttons. Selected creators retain their saved
work card, briefing and contact links. A manual stop or a non-active/non-closed
order state rejects intake immediately.

There is no bulk message editing/deletion job. Historical cards are disabled on
interaction. The existing admin primary-position counter exposes any missing
replacement; closing intake neither fills that vacancy nor reopens dispatch.

## Migration and release

Migration `0148_offer_reserve_window` adds one nullable timestamp. It does not
change payment, order or collaboration status. Historical closed orders retain
NULL and cannot accept reserve responses. Already-full active orders receive
an expired deadline at migration time, preventing a fresh window for old work.
Other active orders start the window when they subsequently fill.

Migrate once before rolling out all affected app/worker versions. Old versions
ignore the additive column, so intake enforcement is guaranteed only after all
response producers are updated. Include Telegram replicas, MAX, the admin
projection, the dispatch consumer and the counteroffer worker as required by
the actual deployed service mapping. Do not deploy from the operational tree.

Application rollback retains the column and deadlines. Database downgrade
refuses to discard non-empty deadlines without an explicit retention decision.
Reverting to an old application restores its old intake behavior; this must be
considered before rollback. Production release requires reviewed PR-head
approval, green CI and the standard verified release procedure.
