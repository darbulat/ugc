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
Offer prices stay distinct from creator proposals. If a proposal changes after
handoff, the current quote and the price at handoff both remain visible.
No second contact list or duplicate refusal/price table is rendered.

The existing 20-second activity refresh updates the workspace and count. It
preserves the active filter, search, focus, expanded details and table scroll.
It pauses during form submission and skips inactive tabs. No new polling loop,
matching scan, notification path, payment operation or migration is introduced.

This change applies to the order card. The reusable direction for person cards
is the same: state and actions first, one authoritative list, details on demand.

Dashboard order queues share `dashboard_order_card.html`: the order, customer,
creation date and responsible managers stay on the left, while reasons, timing
and selection progress stay on the right. Moderation, delayed selection and
unpaid orders use this same structure. Queue colors communicate urgency. Cards
in the same dashboard row align in height and stack on narrow screens.

Manager profiles use `order_managers.html` in the dashboard and order overview.
One manager has one profile link; their Telegram contact appears separately
only when it differs from the displayed name, ignoring case and a leading `@`.
Multiple responsible managers remain separate people. Dashboard managers come
from the same batched assignment query used by the order overview and list.
