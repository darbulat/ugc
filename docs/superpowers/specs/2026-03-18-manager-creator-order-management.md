# Manager: Creator Order Management

**Date:** 2026-03-18
**Status:** Approved

## Summary

Managers need to move creators between the active order list and the reserve list from the mini app's creator detail screen. Removing a creator moves them to reserve (`in_offer=False`); adding a reserve creator to the order sets `in_offer=True` after verifying a free slot exists. Both actions send bot notifications to the creator.

## User Flow

Mini app → Менеджер → Мои заказы → Детали заказа → Креаторы в заказе → *click creator* → Детали креатора → «Убрать из заказа» or «Добавить в заказ»

## Decisions

| Question | Answer |
|---|---|
| Where are the buttons? | On the creator detail screen (not inline in the list) |
| Remove action | Moves to reserve (`in_offer=False`); creator notified |
| Add action | Sets `in_offer=True`; slot check required; creator notified with manager Telegram |
| Confirmation before remove? | Yes — inline warning with «Убрать» / «Отмена» buttons (no `browser.confirm()`) |
| Slot check for add? | Yes — `in_offer_count < bloggers_needed`; return HTTP 409 if no free slot |
| No free slot error | HTTP 409 with `detail="No free slots in this order"` |
| Already in target state | HTTP 409 (e.g. remove when `in_offer=False`, add when `in_offer=True`) |
| Notifications | Both actions notify creator; `/add` also includes manager Telegram |
| Manager Telegram fallback | If `manager_id` is None or manager has no `telegram`: use `"—"` (bare em-dash) |

---

## Data Layer

### New repo method

Add to `OfferDispatchRepository` ABC (`application/ports.py`):

```python
@abstractmethod
async def set_in_offer(
    self,
    order_id: UUID,
    blogger_id: UUID,
    in_offer: bool,
    session: object | None = None,
) -> None:
    """Set in_offer flag on the dispatch for order+blogger."""
```

### SQLAlchemy implementation (`infrastructure/db/repositories/interactions.py`)

```python
async def set_in_offer(
    self,
    order_id: UUID,
    blogger_id: UUID,
    in_offer: bool,
    session: object | None = None,
) -> None:
    async with _resolve_session(self.session_factory, session) as s:
        await s.execute(
            update(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.blogger_id == blogger_id,
            )
            .values(
                in_offer=in_offer,
                updated_at=datetime.now(timezone.utc),
            )
        )
```

### InMemory implementation (`infrastructure/memory_repositories.py`)

```python
async def set_in_offer(
    self,
    order_id: UUID,
    blogger_id: UUID,
    in_offer: bool,
    session: object | None = None,
) -> None:
    key = (order_id, blogger_id)
    if key not in self._dispatches:
        return
    self._dispatches[key] = replace(
        self._dispatches[key],
        in_offer=in_offer,
        updated_at=datetime.now(timezone.utc),
    )
```

---

## InteractionService — new method

Add a new public method to `InteractionService` (`application/services/interaction_service.py`):

```python
async def cancel_interaction(
    self,
    order_id: UUID,
    blogger_id: UUID,
    advertiser_id: UUID,
) -> None:
    """Set interaction to NO_DEAL when creator is removed from order.

    No-op if interaction does not exist or is already in a terminal state
    (OK or NO_DEAL).
    """
    interaction = await self._get_by_participants(
        order_id, blogger_id, advertiser_id
    )
    if interaction is None:
        return
    if interaction.status in (InteractionStatus.OK, InteractionStatus.NO_DEAL):
        return
    now = datetime.now(timezone.utc)
    resolved = replace(
        interaction,
        status=InteractionStatus.NO_DEAL,
        next_check_at=None,
        updated_at=now,
    )
    await self._save(resolved)
    logger.info(
        "Interaction cancelled (creator removed from order)",
        extra={
            "order_id": str(order_id),
            "blogger_id": str(blogger_id),
        },
    )
```

`InteractionStatus`, `replace`, `datetime`, `timezone`, and `logger` are already available in the service file.

---

## Bot Notification Texts

Add to all locale sections in `src/ugc_bot/bot/texts/defaults.py`:

### `msg_creator_removed_from_order`

| Locale | Text |
|---|---|
| ru | `«К сожалению, вы были убраны из заказа менеджером.»` |
| en | `«Unfortunately, you have been removed from the order by the manager.»` |
| kk | `«Өкінішке орай, менеджер сізді тапсырыстан шығарды.»` |
| be | `«На жаль, вас выдалілі з заказу мэнэджарам.»` |
| uz | `«Afsuski, siz menejer tomonidan buyurtmadan chiqarildingiz.»` |

### `msg_creator_added_to_order`

| Locale | Text |
|---|---|
| ru | `«Вас добавили в заказ! Ваш менеджер: {manager_telegram}. Ждём вашего видео.»` |
| en | `«You have been added to the order! Your manager: {manager_telegram}. We look forward to your video.»` |
| kk | `«Сіз тапсырысқа қосылдыңыз! Менеджеріңіз: {manager_telegram}. Бейнеңізді күтеміз.»` |
| be | `«Вас дадалі ў заказ! Ваш мэнэджар: {manager_telegram}. Чакаем вашага відэа.»` |
| uz | `«Siz buyurtmaga qo'shildingiz! Menejeringiz: {manager_telegram}. Videongizni kutamiz.»` |

`{manager_telegram}` is formatted as `@{telegram}` if `manager.telegram` is not None, else `"—"` (bare em-dash).

---

## API

Both endpoints follow the existing mini-app pattern: POST with `init_data` in the request body. Manager must be assigned to the order (`is_manager_for_order` check).

### Extend `CreatorDetailResponse`

Add `in_offer: bool` to the existing `CreatorDetailResponse` model:

```python
class CreatorDetailResponse(BaseModel):
    blogger_id: str
    instagram_url: str | None = None
    telegram: str | None = None
    ugc_video_url: str | None = None
    in_offer: bool                    # new
```

The existing `manager_creator_detail` endpoint must be updated to populate `in_offer=dispatch.in_offer` in the return statement:

```python
return CreatorDetailResponse(
    blogger_id=str(blogger_id),
    instagram_url=profile.instagram_url if profile else None,
    telegram=user.telegram if user else None,
    ugc_video_url=dispatch.ugc_video_url,
    in_offer=dispatch.in_offer,    # new
)
```

### `POST /api/manager/orders/{order_id}/creators/{blogger_id}/remove`

Removes a creator from the active order (moves to reserve).

**Request body:**
```json
{ "init_data": "<telegram-init-data>" }
```

**Response:**
```json
{ "ok": true }
```

**Logic:**
1. Validate manager is assigned to order (`is_manager_for_order`). Return 403 if not.
2. Fetch order via `order_repo.get_by_id(order_id)`. Return 404 if not found.
3. Call `dispatch_repo.get_by_order_and_blogger(order_id, blogger_id)`.
   - If `None`: return HTTP 404.
   - If `dispatch.in_offer == False`: return HTTP 409 (`"Creator is already in reserve"`).
4. Call `dispatch_repo.set_in_offer(order_id, blogger_id, False)`.
5. Call `interaction_service.cancel_interaction(order_id, blogger_id, order.advertiser_id)`.
6. Fetch creator `User` via `user_repo.get_by_id(blogger_id)`.
7. If creator found:
   a. Determine locale: `creator.language or "ru"`.
   b. Fetch text via `bot_texts_service.get("msg_creator_removed_from_order", locale)`.
   c. Send via `send_with_retry(messenger_client, chat_id=creator.external_id, text=text, retries=3, delay_seconds=1, logger=logger, extra={"event": "creator_removed_from_order"})`.
8. If creator not found: log warning, skip notification.

`interaction_service` is obtained from `dispatcher["interaction_service"]`.

**Request model:** `InitDataBody` (existing model — `init_data: str`).

### `POST /api/manager/orders/{order_id}/creators/{blogger_id}/add`

Adds a reserve creator to the active order.

**Request body:**
```json
{ "init_data": "<telegram-init-data>" }
```

**Response:**
```json
{ "ok": true }
```

**Logic:**
1. Validate manager is assigned to order (`is_manager_for_order`). Return 403 if not.
2. Fetch order via `order_repo.get_by_id(order_id)`. Return 404 if not found.
3. Call `dispatch_repo.get_by_order_and_blogger(order_id, blogger_id)`.
   - If `None`: return HTTP 404.
   - If `dispatch.in_offer == True`: return HTTP 409 (`"Creator is already in the order"`).
4. Check free slot: `in_offer_count = await dispatch_repo.count_accepted_by_order(order_id)`.
   - If `in_offer_count >= order.bloggers_needed`: return HTTP 409 (`"No free slots in this order"`).
5. Call `dispatch_repo.set_in_offer(order_id, blogger_id, True)`.
6. Fetch creator `User` via `user_repo.get_by_id(blogger_id)`.
7. Fetch manager `User` via `user_repo.get_by_id(dispatch.manager_id)` if `dispatch.manager_id` is not None.
8. Format `manager_telegram`:
   - If manager found and `manager.telegram` is not None: `f"@{manager.telegram}"`
   - Else: `"—"`
9. Fetch locale: `creator.language or "ru"`.
10. Fetch text via `bot_texts_service.get("msg_creator_added_to_order", locale)`.
11. Format text: `template.format(manager_telegram=manager_telegram)`.
12. Send via `send_with_retry(messenger_client, chat_id=creator.external_id, text=text, retries=3, delay_seconds=1, logger=logger, extra={"event": "creator_added_to_order"})`.
13. If creator not found: log warning, skip notification.

Both endpoints use **`InitDataBody`** (existing model in `api.py` — `init_data: str`) as the request body model.

---

## Frontend (`miniapp/app.html`)

### `CreatorDetailResponse` now includes `in_offer`

`openCreatorDetail` already calls `POST .../creators/{bloggerId}` and renders the detail screen. After this change, `data.in_offer` is available.

### Conditional button rendering

In `openCreatorDetail`, after rendering the UGC video section, add a management section based on `data.in_offer`:

**If `data.in_offer === true`:** render «Убрать из заказа» button (red/danger style). On click, replace button with inline confirmation block containing:
- Warning text: `«Убрать @{telegram} из заказа? Он переместится в резерв.»`
- «Убрать» confirm button → calls `removeCreatorFromOrder(orderId, bloggerId)`
- «Отмена» cancel button → restores original button

**If `data.in_offer === false`:** render «Добавить в заказ» button (green/success style). On click, calls `addCreatorToOrder(orderId, bloggerId)` directly (no confirmation needed).

### New JS functions

**`removeCreatorFromOrder(orderId, bloggerId)`**
- Calls `POST .../creators/{bloggerId}/remove` with `{ init_data: initData }` (uses the global `initData` variable already available in the mini app)
- On success: shows `«✅ Убрано из заказа»` status, then after 1 second calls `loadManagerCreators(orderId, true, 0)` and shows creators screen

**`addCreatorToOrder(orderId, bloggerId)`**
- Calls `POST .../creators/{bloggerId}/add` with `{ init_data: initData }`
- On success: shows `«✅ Добавлен в заказ»` status, then after 1 second calls `loadManagerCreators(orderId, false, 0)` and shows creators screen
- On 409 error: shows `«❌ Нет свободных слотов»`

All DOM manipulation uses safe methods only (`createElement`, `textContent`, `setAttribute`, `appendChild`) — no `innerHTML`.

---

## Testing

### Unit tests (`tests/unit/test_creator_order_management.py`)

- `test_set_in_offer_updates_value` — InMemory repo: call `set_in_offer(order_id, blogger_id, False)`, then fetch via `get_by_order_and_blogger` and assert `dispatch.in_offer == False`.
- `test_set_in_offer_noop_when_missing` — no exception if dispatch doesn't exist.
- `test_cancel_interaction_sets_no_deal` — InMemory: create PENDING interaction, call `cancel_interaction`, assert status is NO_DEAL.
- `test_cancel_interaction_noop_when_already_terminal` — interaction already NO_DEAL; assert no update called.
- `test_cancel_interaction_noop_when_not_found` — no interaction exists; assert no exception.
- `test_remove_endpoint_moves_to_reserve` — mock repo and messenger; call remove endpoint; assert `set_in_offer` called with `False`, `cancel_interaction` called, creator notified.
- `test_remove_endpoint_409_already_in_reserve` — dispatch has `in_offer=False`; assert HTTP 409.
- `test_remove_endpoint_404_dispatch_missing` — dispatch is None; assert HTTP 404.
- `test_add_endpoint_moves_to_active` — free slot available; assert `set_in_offer` called with `True`, creator notified with manager telegram.
- `test_add_endpoint_409_no_free_slots` — `in_offer_count >= bloggers_needed`; assert HTTP 409.
- `test_add_endpoint_409_already_in_order` — dispatch has `in_offer=True`; assert HTTP 409.
- `test_add_endpoint_404_dispatch_missing` — dispatch is None; assert HTTP 404.
- `test_add_notification_includes_manager_telegram` — manager has telegram; assert `@manager_tg` in notification text.
- `test_add_notification_manager_not_found_uses_dash` — manager_id is None; assert `«—»` in notification text.

### Existing suite

Run `make fix` after implementation; 98% coverage threshold must pass.
