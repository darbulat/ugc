# Financial v1 ledger and coordination ADR — 2026-10-22

Status: implementation contract, NOT release approval. Normative source: Financial v1 spec 1.2, D-01–D-10. All new runtime gates default false. No historical money conversion/backfill.

## Journal representation

One append-only journal carries typed economic events (`issuance`, `reversal`, `debt`, `recovery`) and positive-amount `transfer` events between named buckets. A transfer is not additional income. Issuance enters pending; reversals reference an original entry/refund/case and cannot exceed the remaining economic amount. Paid is historical, never transferred back or rewritten: an economic cancellation affecting paid creates separate case/debt. Recovery records an actual recipient repayment, not an invented future offset. All amounts are integer minor units with explicit currency; no cross-currency sums.

Journal rows are immutable in services AND through restricted DB application-role privileges. Future journal migration must deny UPDATE/DELETE (including admin generic CRUD); this ADR alone does not implement DB privileges. Mutable projections must replay exactly. Runtime payouts remain disabled until those migrations/replay checks exist.

Each event includes operation key, event ID, actor, reason, effective/recorded UTC timestamps, obligation, source entry when compensating, and explicit request/allocation/execution IDs for reserves/consumption. Refund/case/source IDs, allocation releases and block/unblock events must be durable immutable events, not only updates to a payout allocation. Same operation key and canonical payload hash returns original result; changed payload conflicts and is audited. Several different corrections may reference the same obligation. Event ID alone is not the business key.

Human/admin journal attribution carries a real non-nil user UUID; system events instead carry an explicit named producer and `actor_id=None`, never a fabricated system user. These fields provide provenance, not authorization: command-layer permissions are derived from verified ingress and current server-side roles. UTC-normalized instants and positive signed-BIGINT minor amounts are required. Cancelled/paid history cannot be resurrected by a bucket transfer; an economic correction must be explicit. Corrections and reserve/paid consumption retain typed source/request/allocation/execution references.

The nullable `financial_version` bridge is an explicitly assigned approved-policy marker in this foundation, not a global feature-switch projection. Legacy rows remain NULL. Consumers must validate the referenced policy/items and must not infer a protocol version by comparing an arbitrary policy label with the literal `"v1"`. Unknown markers fail closed rather than falling back to legacy writers.

For each recipient AND currency: **G − V − F + R = U − D**. G = recognized issuance, V = economic reversals (including paid), F = confirmed bank payouts, R = actual debt repayments; U = pending+hold+available+reserved+blocked; D = remaining post-payment debt. Cancelled records V's history, not U. No `max(balance, 0)` masking. Discrepancy blocks a new payout and raises reconciliation alert.

## Shared legacy/v1 writer barrier and lock order

1. Lock **UserModel recipient rows FOR NO KEY UPDATE**, sorted by recipient UUID. This is the existing legacy wallet barrier and MUST precede all v1 locks. Currency-wallet locking alone cannot coordinate legacy writers.
2. Lock/create recipient+currency wallet rows in deterministic recipient/currency order.
3. Lock items sorted by UUID (and capture/payment coordination rows consistently within the command).
4. Lock obligations sorted by UUID.
5. Lock payout requests sorted by UUID.
6. Re-read versions, available amounts, durable guard/case/inbox state and eligibility only after locks, then append journal, update projections and outbox within the same caller transaction.

PostgreSQL `FOR NO KEY UPDATE` is an exclusive writer mutex, not `FOR KEY SHARE`. It remains compatible with FK `KEY SHARE` locks already acquired by complaint/actor inserts. `with_for_update(key_share=True)` with `read=False` renders this mode in SQLAlchemy. The real two-session complaint/wallet regression reproduced a deadlock with the stronger old `FOR UPDATE`; both wallet mutation and payout paths now share the exclusive FK-compatible mode.

Legacy operational commands may already hold their legacy order/dispatch/interaction locks before this barrier. Before activation, cutover must reject legacy financial mutations for v1-owned orders. A v1 command must not acquire a legacy coordination lock after wallet locks while a legacy command can still acquire those same locks in reverse order. All such multi-model paths require the same version-aware writer cutoff and independent-session race coverage; this ADR is not evidence that the future integration is complete.

No new v1 payout is permitted until **every** legacy and v1 writer obeys the common user-row barrier, including rollback/cutover/reconciliation. LegacyFinancialGuard is durable and has no automatic release. This foundation does not replace or relax it. No lock is held across bot, S3, provider or bank I/O. External operations occur after commit, via outbox/inbox and reconciliation; unknown results never authorize duplicate transfers or reserve release.

## Policy, capture and quotes

Published policy is versioned and immutable. Refund-window duration is a required published input, not a default. selection_due_at is agreed per order before capture; there is no global default deadline. Technical activation, allowlist, approved terms and policy are independent prerequisites. Old and pre-activation unpaid orders remain legacy. No automatic import of legacy overrides. New overrides/nonstandard prices return policy_feature_disabled.

Quote item IDs/components, currency, policy, due date and protected contact/terms references are snapshotted before capture. Standard v1 tariff is RUB only: selection=50000, optional accompaniment=120000; referral basis is selection only. Payment's legacy decimal amount is never converted into captured_minor automatically. Capture integration must verify trusted channel/signature, provider/account scope, order ownership, exact amount and currency before setting the new explicit fields. Partial/overcapture cannot silently unlock items.

Allocation composite FKs bind both payment and item to the same order/currency. Positive amounts/component checks, one component allocation per item and payment-row serialization guard against overspend. One current assignment per item is a PostgreSQL partial unique index; replacements retain item ID and history. DB constraints do not replace authorization, policy validation or trusted capture; those integrations remain separate release gates.

## Release boundary

Tasks 11–15 provide foundation only, not the complete B lifecycle. No CoreActivation, production migration, payout activation, automatic refunds, fabricated legal approvals or bank integrations are authorized here. Snapshot/ledger/capture ingress, replay reconciliation, shared barrier coverage, operational parameters, legal process and complete acceptance gates must be verified before any real new financial sale.
