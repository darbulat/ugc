# Manual creator handoffs

The order workspace has an explicit **«Отправить заказчице»** action for a
confirmed reserve creator or a creator's counteroffer. It also works on closed
paid orders. Sending a counteroffer presents its price as requiring agreement;
it does not accept that price on the customer's behalf.

**«Передано авторов: 15 из 10»** counts unique creators whose contacts have
actually been released to the current order owner. It includes original
provider-accepted contact deliveries, previously opened replacement contacts
and successful supplemental sends. Refusals, replacements and refunds do not
remove earlier deliveries. Retransmitting a known creator does not add another
person. Original contact snapshots remain available after assignment/profile
changes. Existing externally entered contacts remain in their current handoff
flow until a creator identity is confirmed.

The new `order_creator_transfers` table records the operator, contact snapshot,
requested price, delivery attempt, Telegram receipt and customer feedback.
Only provider acceptance increments the counter. Concurrent clicks are fenced
by the existing user-before-order locking convention and a unique order/creator
key. Definite transport rejection allows another explicit click. An ambiguous
send or expired in-flight attempt is displayed as unknown and is not retried
automatically. No background delivery worker or polling service is added; the
admin's existing 20-second activity refresh updates the figures.

Supplemental handoffs do not create paid items, assignments, charges, refunds,
accruals or referral rewards. Customer feedback on supplemental work is an
operational attestation: «Работали», «Не работали», «Не договорились». A customer
can rate supplemental work after marking that they worked together, including
after order closure. This feedback never confirms a financial collaboration.
Existing paid collaboration completion/settlement rules remain authoritative.

Expired no-answer exceptions now go to the existing support review queue.
The 24-hour notice remains; the scheduler no longer selects a reserve creator
or calls the automatic financial replacement command. Manual paid replacement
commands retain their existing policy checks.

## Release

Migration `0144_manual_creator_transfers` only adds a table and its history
preservation guards; it does not rewrite existing order or money facts. Old
services can continue running against this schema. Obtain approval for the
current PR head and migration before merging/releasing, per `AGENTS.md`.

After taking the configured backup and applying the migration once, update the
combined scheduler first (manual escalation), then `app` and `app_2` using the
existing rolling procedure, and finally `admin`. Confirm actual live service
mapping and preserve operational Compose files/environment. Deploy the new
admin action only after customer views understand supplemental contacts.

Verify an authenticated read of the existing ReBody order: its previous contacts
and original quota are present, reserve and counteroffer actions are available,
and no customer message was sent by viewing the card. The first real send is a
deliberate operator action. Database and browser tests use synthetic users and
fake Telegram transports; they do not notify the real customer.

Keep the new table on rollback so successful handoffs are not lost. If reverting
the web/admin images, retain the scheduler's manual escalation behavior rather
than restoring automatic reserve selection. Never downgrade away recorded
handoff history.
