# Order workspace layout

The overview distinguishes paid positions from unique creators whose contacts
were delivered. Its compact count shows `15 / 10`, a capped blue progress bar
and a red `+5 сверх плана` label. Overdelivery does not change the paid quota.
Paid status belongs in the overview. Unfinished browser payments retain their
existing controls, review warnings, copy actions and status refresh.

One creator UUID owns one table row across responses, financial assignments,
counteroffers and historical handoffs. Response, proposed price, delivery and
work remain separate facts. Filters are mutually exclusive: delivered authors,
untransferred reserve, untransferred counteroffers, refusals and assignments
awaiting their normal contact delivery. Search and filter changes are local.

Delivered contact snapshots stay authoritative in the row. Phone, response
date and changed current profile details open in that row. Old names, profiles,
phones, replacement sources, feedback and video links remain accessible.
No second contact list or duplicate refusal/price table is rendered.

The existing 20-second activity refresh updates the workspace and count. It
preserves the active filter, search, focus, expanded details and table scroll.
It pauses during form submission and skips inactive tabs. No new polling loop,
matching scan, notification path, payment operation or migration is introduced.

This change applies to the order card. The reusable direction for person cards
is the same: state and actions first, one authoritative list, details on demand.
