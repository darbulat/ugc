# Order Managers — Design Spec

**Date:** 2026-03-15
**Status:** Approved

## Overview

Система привязки менеджеров к заказам. Менеджеры получают отклики креаторов по round robin, видят своих креаторов через mini app. Рекламодатель продолжает получать все отклики.

## Requirements

1. В админке при редактировании заказа — текстовое поле для ввода @username менеджеров через запятую. Валидация: если пользователь с таким telegram не найден в `users` — ошибка.
2. При отклике креатора на заказ — round robin назначает менеджера. Менеджер получает тот же контент что рекламодатель (карточка креатора). Рекламодатель продолжает получать все отклики.
3. Связь креатор↔менеджер сохраняется в `offer_dispatches.manager_id` для определения вознаграждения менеджеру в будущем.
4. В mini app: кнопка "Менеджер" (если пользователь привязан к заказам), пагинированный список заказов, просмотр своих креаторов (in_offer / резерв).

## Data Model

### New table: `manager_orders`

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | UUID, FK → users, PK | Manager |
| `order_id` | UUID, FK → orders, PK | Order |
| `created_at` | datetime | Created timestamp |
| `updated_at` | datetime | Updated timestamp |

Composite PK: `(user_id, order_id)`.

### New field in `orders`

- `last_round_robin_index: int, default 0` — counter for round robin rotation

### New field in `offer_dispatches`

- `manager_id: UUID, FK → users, nullable` — manager assigned to this response via round robin. NULL if order has no managers.

### New domain entity

```python
@dataclass(frozen=True)
class ManagerOrder:
    user_id: UUID
    order_id: UUID
    created_at: datetime
    updated_at: datetime
```

### Changes to existing entity

`OfferDispatch`: add `manager_id: Optional[UUID] = None`

## Application Layer

### New port: `ManagerOrderRepository`

```python
class ManagerOrderRepository(ABC):
    async def list_by_order(self, order_id: UUID) -> list[ManagerOrder]
    async def list_by_user(self, user_id: UUID) -> list[ManagerOrder]
    async def save(self, manager_order: ManagerOrder) -> None
    async def delete_by_order(self, order_id: UUID) -> None
    async def exists_for_user(self, user_id: UUID) -> bool
```

### Changes to `OfferDispatchRepository`

New method:
```python
async def list_responses_by_order_and_manager(
    self, order_id: UUID, manager_id: UUID, in_offer: bool
) -> list[OfferDispatch]
```

### New service: `ManagerService`

```python
class ManagerService:
    def __init__(self, manager_order_repo, user_repo):
        ...

    async def set_managers_for_order(
        self, order_id: UUID, telegram_usernames: list[str]
    ) -> None:
        """Validate usernames against users.telegram, delete old records, create new.
        Raises ValueError if username not found in users."""

    async def get_next_manager(self, order: Order) -> Optional[User]:
        """Round robin: get managers for order, select by last_round_robin_index % len(managers)."""

    async def is_manager(self, user_id: UUID) -> bool:
        """Check if user has any records in manager_orders."""

    async def list_orders_for_manager(
        self, user_id: UUID, limit: int, offset: int
    ) -> list[Order]:
        """Paginated list of orders for a manager."""
```

### Changes to `OfferResponseService.respond_and_finalize()`

After recording the response:
1. Get managers for the order
2. If managers exist — call `get_next_manager()`, increment `last_round_robin_index`
3. Write `manager_id` into `offer_dispatch`
4. Return `manager: Optional[User]` in `OfferResponseResult`

## Notification Flow

### Changes to `_send_contact_immediately()`

Add parameter `manager: Optional[User]`. Send order:
1. Advertiser — creator card (unchanged)
2. Manager — same `contact_text` + `open_profile_kb` via `send_with_retry()` (3 retries, 0.5s delay)
3. Creator — advertiser contacts (unchanged)

Manager receives the same content as advertiser. If no manager assigned — skip step 2.

## Admin Panel

### Custom field on Order edit form

In `OrderAdmin`:
1. Add custom `managers` StringField — not mapped to a model column
2. On form open (`on_form_prefill` or similar): load current managers from `manager_orders`, display as `@username1, @username2`
3. On save (`update_model()`):
   - Parse string: split by comma, strip whitespace, remove `@` prefix
   - For each username: `user_repo.get_by_telegram(username)`
   - If not found: `raise ValueError(f"Пользователь с Telegram @{username} не найден в базе")`
   - Call `manager_service.set_managers_for_order(order_id, usernames)`

Error display uses existing pattern — `ValueError` from `update_model()` shown via `context["error"]`.

## Mini App

### Button visibility

In `/me` endpoint response: add `is_manager: bool` field.
Value: `manager_service.is_manager(user_id)`.

In `app.html` on `screen-role-choice`: if `is_manager=True`, show third button "Менеджер" after "Рекламодатель" and "Креатор".

### New screens

**screen-manager-orders** — paginated order list:
- Load: `POST /miniapp/api/manager/orders` with `{init_data, limit, offset}`
- Each item: product_link, price, status, creator count
- Pagination: "Назад" / "Ещё"
- Click → `screen-manager-order-detail`

**screen-manager-order-detail** — two buttons:
- "Креаторы в заказе" → creators list with `in_offer=true`
- "Креаторы в резерве" → creators list with `in_offer=false`

**screen-manager-creators** — paginated creator list:
- Load: `POST /miniapp/api/manager/orders/{order_id}/creators` with `{init_data, in_offer, limit, offset}`
- Each item: `instagram_url` (link), `@telegram` (link)
- Filter: `WHERE manager_id = current_user_id AND order_id = ? AND in_offer = ?`
- Manager sees only their own assigned creators

### New API endpoints

```
POST /miniapp/api/manager/orders
  Request: {init_data, limit: int, offset: int}
  Response: {orders: list[OrderListItem], total: int}

POST /miniapp/api/manager/orders/{order_id}/creators
  Request: {init_data, in_offer: bool, limit: int, offset: int}
  Response: {creators: list[CreatorItem], total: int}
```

`CreatorItem`: `{instagram_url: str, telegram: str}`

Both endpoints validate that current user is a manager for the given order.

## Testing

### Unit tests
- `ManagerService.set_managers_for_order()` — username validation, error on not found
- `ManagerService.get_next_manager()` — round robin (0→A, 1→B, 2→C, 3→A)
- `OfferResponseService.respond_and_finalize()` — verify `manager_id` written to `offer_dispatch`
- In-memory `MemoryManagerOrderRepository` in `infrastructure/memory_repositories.py`

### Integration tests
- Manager assignment via admin — save/load cycle
- Round robin with real DB
- Mini app endpoints with pagination

## Round Robin Algorithm

```
managers = sorted(list_by_order(order_id), key=lambda m: m.created_at)
index = order.last_round_robin_index % len(managers)
selected = managers[index]
order.last_round_robin_index += 1
```

Deterministic ordering by `created_at` ensures consistent rotation.
