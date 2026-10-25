# Marketing evidence and performance

A01 records manual evidence for an owned campaign or order. It does not modify
platform balances, fees, payout liabilities or the financial journal. An active
administrator publishes an immutable source with source/account identifiers,
explicit attribution window, actual marketing spend in minor units, measured
metrics, spend reference, evidence reference and reason. A spend reference cannot
fund two active sources in the same account. Corrections void the old source and
publish new evidence; history remains intact.

Supported currencies use two decimal minor units: RUB, USD, EUR, KZT, BYN and UZS.
A subject cannot mix currencies. Unsupported currencies fail closed rather than
assuming an exchange rate or minor-unit scale.

Import at most 1000 events per operation through the signed MiniApp. Events carry
an external event ID, event timestamp, entity ID, kind, positive quantity and,
for sales/refunds, the actual amount. Only events within the source window and
not in the future are accepted. The source/account/event ID is globally unique;
repeating identical evidence is harmless and changed evidence conflicts. Leads
and sales require unique entity IDs within the subject. Refunds must reference
an earlier sale in the same account and cannot exceed its paid amount.

Sources remain partial until an administrator finalizes their completed window
with reconciliation evidence. Finalized sources cannot accept additional events;
a new source can contain later evidence. Voiding a sale source while retaining
its refund evidence marks the report as requiring review and suppresses rates.
CPV/CPL/CPA use actual marketing spend divided by views, distinct leads and sales
with positive paid amount after refunds. Rates require complete coverage of that
metric by every active source. Missing data, incomplete sources and zero
denominators produce null rates, never invented zero-cost performance.

Owners can read their own aggregate report. An unrelated administrator cannot
read an owner's report through that route. Administrative evidence forms require
current server authority; an old client role does not grant access. Reports do
not export contacts, account identifiers or evidence references. Signed requests
reject extra fields and query overrides and every response is `no-store`.

A separate immutable manual paid-pilot receipt records actual payment reference,
amount, currency and proof. Each subject and payment reference count once. The
report explicitly exposes the count and only confirms the original minimum of
two paid campaigns after recorded evidence exists. Synthetic tests do not count
as real paid campaigns or customer demand. Operations must still run and verify
the original two to three paid campaign pilots before claiming commercial proof.
