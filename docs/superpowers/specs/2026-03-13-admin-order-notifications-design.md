# Admin Order Notifications — Design Spec

**Date:** 2026-03-13
**Branch:** claude/admin-order-notifications-5HTny
**Status:** Approved

## Problem

Admins receive no notification when an order is created. The existing
`notify_admins_about_new_order` fires only after payment is confirmed
(`successful_payment_handler`). This means:

- Barter orders (`COOP_BARTER`) never trigger an admin notification because
  no payment step is taken by the advertiser.
- Paid orders (`COOP_PAYMENT`, `COOP_BOTH`): admins see nothing until payment.

## Goal

Send admins two distinct notifications:

1. **On creation** (all cooperation formats) — "new order" with no Activate button.
2. **On payment confirmed** (`COOP_PAYMENT` and `COOP_BOTH`) — "order paid,
   ready for moderation" with Activate button.

`COOP_BARTER` orders only ever receive notification #1; since the advertiser
still pays the platform fee invoice, the payment handler does not fire the
"order paid" notification for barter orders. The distinction is: notification
#2 fires inside `successful_payment_handler` after `confirm_telegram_payment`,
which is not reachable for pure barter.

Support-chat notifications are unaffected.

## Design

### 1. `admin_notification_service.py`

Extract shared text body into a private helper:

```python
def _build_order_admin_text(
    order: Order,
    advertiser_name: str,
    currency_symbol: str,
    banned_warning: str,
) -> str:
    """Return the HTML body for an order notification (no header, no buttons).

    Includes: order ID, advertiser, order type, offer text, product link,
    barter, price, bloggers needed, content usage, deadlines, geography,
    and the banned_warning suffix.
    """
```

Each public function is responsible for:
1. Fetching `advertiser_name` from `user_role_service`.
2. Computing `banned_warning` via `content_moderation.order_contains_banned_content(...)`.
3. Calling `_build_order_admin_text(order, advertiser_name, currency_symbol, banned_warning)`.
4. Prepending its own header to the result.
5. Building its own button set.
6. Dispatching per admin (photo branch if `order.product_photo_file_id` set,
   else text).

The photo-vs-text dispatch (2-line if/else) is duplicated in each public
function — not worth abstracting.

---

**New function** `notify_admins_about_order_created`:
- Header: `"📋 <b>Новый заказ</b>"` — no "на модерацию" suffix
- Buttons: "Открыть в админке" only (if `admin_base_url` set); no "Активировать"
- Same signature as `notify_admins_about_order_paid`

---

**Renamed + modified function** `notify_admins_about_order_paid`
(was `notify_admins_about_new_order`):

Two changes from the current function:
1. **Renamed** from `notify_admins_about_new_order`.
2. **Header text changed** from `"📋 <b>Новый заказ на модерацию</b>"` to
   `"✅ <b>Заказ оплачен — на модерацию</b>"`.

Buttons remain unchanged: "Открыть в админке" + "Активировать".

### 2. `bot/handlers/order_creation.py`

Add `notify_admins_about_order_created` call **immediately after
`order_service.create_order(...)` succeeds**, before the support-chat
notification and before `state_store.clear()`. This fires for all cooperation
formats (`COOP_PAYMENT`, `COOP_BARTER`, `COOP_BOTH`):

```python
order = await order_service.create_order(...)

await notify_admins_about_order_created(
    order=order,
    messenger_client=messenger_client,
    user_role_service=user_role_service,
    content_moderation=content_moderation_service,
    admin_base_url=config.admin.admin_base_url,
    currency_symbol=config.market.currency_symbol,
)
# ... then support chat, then state_store.clear(), then invoice
```

Add `content_moderation_service: ContentModerationService` as a new injected
parameter to the handler function (the final FSM step that calls
`create_order`). Registered in the DI container under key
`"content_moderation_service"` — confirmed in `container/service_factory.py:306`
and `container/types.py:46`.

**All existing tests** for this handler function that call it with explicit
keyword arguments must add `content_moderation_service=...` to their call sites.

### 3. `bot/handlers/payments.py`

Replace import and call:

```python
# Before
from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_new_order,
)
await notify_admins_about_new_order(...)

# After
from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_order_paid,
)
await notify_admins_about_order_paid(...)
```

No other logic changes.

## Error Handling

Both notification functions already swallow per-admin exceptions with
`logger.warning`. No changes needed.

## Testing

### Unit tests (`tests/application/services/test_admin_notification_service.py`)

**`notify_admins_about_order_paid`** (renamed from `notify_admins_about_new_order`):
- Update import to `notify_admins_about_order_paid`.
- Rename all test functions accordingly.
- Update header assertion from `"Новый заказ на модерацию"` to `"Заказ оплачен"`.
- Verify "Активировать" button present.

**`notify_admins_about_order_created`** (new tests):
- Header contains `"Новый заказ"` AND does **not** contain `"на модерацию"`
  (both functions share the `"Новый заказ"` prefix, so the negative assertion
  is required to distinguish them).
- No "Активировать" button in any keyboard row.
- "Открыть в админке" button present when `admin_base_url` is set.
- No "Открыть в админке" when `admin_base_url` is empty.
- No admins → function returns without sending.
- Order with `product_photo_file_id` set → `send_photo` used, not `send_text`.

### Handler tests

**`order_creation.py` handler:**
- `COOP_PAYMENT` path: `notify_admins_about_order_created` called once;
  `notify_admins_about_order_paid` not called.
- `COOP_BARTER` path: `notify_admins_about_order_created` called once;
  `notify_admins_about_order_paid` not called.
- `COOP_BOTH` path: `notify_admins_about_order_created` called once;
  `notify_admins_about_order_paid` not called.

**`payments.py` handler:**
- `successful_payment_handler`: `notify_admins_about_order_paid` called once
  after successful payment.

## Out of Scope

- Support-chat notifications (`notify_support_chat_about_new_order`) — no changes.
- Admin moderation callback (`MOD_ACTIVATE_CALLBACK_PREFIX`) — no changes.
- `COOP_BARTER` orders never reach `successful_payment_handler`, so
  `notify_admins_about_order_paid` is intentionally never called for them.
  Admins use the creation notification to review and activate barter orders.
