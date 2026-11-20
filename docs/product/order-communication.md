# Order communication and response copies

The order owner, public customer name and creator's work contact have separate
purposes. An administrator can set a public customer name such as
`UseMyContent` without publishing a personal Telegram name. This label is
optional and appears on the public offer; the product brand remains a separate
approved field.

The creator-card section of the order editor selects who communicates:

| Selection | Contact revealed after the response |
| --- | --- |
| Client | The saved client Telegram |
| Manager | The saved manager Telegram |
| Existing work contact | The original card contact, for existing cards |

Each role retains its own Telegram so changing the selection cannot reuse the
other party's contact. A selected role requires a valid Telegram before
activation. There is no fallback from a missing manager contact to the client.
Both contacts stay hidden before the response. The selected contact is also
saved in the original `contact` field for compatibility during rolling updates.
The settings reuse `orders.creator_offer_card`; no migration is required.

For a direct response (including the existing MyLittleChair draft), the client
and the creator's assigned manager each receive a response card. Round-robin
assignment still selects one manager when the order has several managers.
Each recipient receives one message through their available preferred
messenger; duplicate identities or destinations are suppressed. A failed send
does not prevent the other recipient's attempt. These direct notifications
retain the existing immediate, best-effort delivery model.

Choosing the communicator does not change these recipients. It controls only
the creator's work contact. It also does not transfer ownership or grant
access to an order. An actual business account must own the draft if that
account should receive the client copy.

Paid contact deliveries retain their existing durable worker and acceptance
rules. This change does not add manager copies to the paid delivery queue.
