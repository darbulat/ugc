# Order progress outside the card

Order lists, order analytics and the dashboard's existing delayed-order rows
show the unique people whose contacts have been delivered, including saved
replacements and successful manual handoffs. One person counts once per order.
Failed, sending and unknown handoffs do not count as delivered.

The blue bar tracks current assigned positions against the original plan and
caps at 100%. A separate count can show `15 / 10` with `+5` above plan. When the
two counts differ, the current plan count stays visible. Billing, quota,
historical contacts and the existing order classifications retain their rules.

Visible financial orders share one batched read of delivery sources and active
positions. Schema compatibility uses one availability query. Legacy orders and
older saved dashboard snapshots retain a labelled selection-count fallback.
No new polling loop or migration is introduced.

The position queue tracks each planned place: selection, contact confirmation,
deadlines, problems and the responsible manager. Extra manually delivered
people remain in the order card. The selected-order scope is a centred badge.

Contact details compare social profile identities rather than URL spelling.
Only genuinely changed fields appear below the saved contacts. Original
snapshots and both spellings used for contact search remain available.
