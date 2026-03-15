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

### New domain entities / changes

```python
@dataclass(frozen=True)
class ManagerOrder:
    user_id: UUID
    order_id: UUID
    created_at: datetime
    updated_at: datetime
```

Changes to existing entities:
- `Order`: add `last_round_robin_index: int = 0`
- `OfferDispatch`: add `manager_id: Optional[UUID] = None`

### Alembic migration

Single migration (next sequential number) that:
1. Creates `manager_orders` table
2. Adds `last_round_robin_index` column to `orders` (default 0)
3. Adds `manager_id` column to `offer_dispatches` (nullable FK → users)

## Application Layer

### New port: `ManagerOrderRepository`

```python
class ManagerOrderRepository(ABC):
    async def list_by_order(self, order_id: UUID) -> list[ManagerOrder]
    async def list_by_user(self, user_id: UUID) -> list[ManagerOrder]
    async def count_by_user(self, user_id: UUID) -> int
    async def save(self, manager_order: ManagerOrder) -> None
    async def delete_by_order(self, order_id: UUID) -> None
    async def exists_for_user(self, user_id: UUID) -> bool
```

### Changes to `OfferDispatchRepository`

New methods:
```python
async def list_responses_by_order_and_manager(
    self, order_id: UUID, manager_id: UUID, in_offer: bool,
    limit: int, offset: int,
) -> list[OfferDispatch]

async def count_responses_by_order_and_manager(
    self, order_id: UUID, manager_id: UUID, in_offer: bool,
) -> int
```

Change to existing method:
- `record_response()`: add parameter `manager_id: Optional[UUID] = None`. Updated in both abstract port and SQLAlchemy implementation to include `manager_id` in the `.values(...)` clause.

### New service: `ManagerService`

```python
class ManagerService:
    def __init__(self, manager_order_repo, user_repo, order_repo):
        ...

    async def set_managers_for_order(
        self, order_id: UUID, telegram_usernames: list[str]
    ) -> None:
        """Validate usernames against users.telegram, delete old records, create new.
        Raises ValueError if username not found in users."""

    async def get_next_manager_id(self, order: Order) -> Optional[UUID]:
        """Round robin: get managers for order, select by last_round_robin_index % len(managers).
        Returns just the user_id — no need to load full User entity in transaction path."""

    async def is_manager(self, user_id: UUID) -> bool:
        """Check if user has any records in manager_orders."""

    async def list_orders_for_manager(
        self, user_id: UUID, limit: int, offset: int
    ) -> tuple[list[Order], int]:
        """Paginated list of orders for a manager. Returns (orders, total_count)."""
```

### Changes to `OfferResponseService.respond_and_finalize()`

**Inside the existing transaction** (which holds a row lock via `get_by_id_for_update`):
1. Get managers for the order via `manager_order_repo.list_by_order()`
2. If managers exist — call `get_next_manager_id()`, get `manager_id`
3. Increment `last_round_robin_index` on the order via `dataclasses.replace()` (same pattern as existing order field updates)
4. Pass `manager_id` to `record_response()` call
5. Save the updated order (with new `last_round_robin_index`)

This ensures atomicity: round robin selection, index increment, and manager_id write all happen under the same row lock, preventing race conditions on concurrent responses.

**After the transaction:**
- If `manager_id` is set, resolve full `User` entity for notification
- Add `manager: Optional[User] = None` to `OfferResponseResult` dataclass

### Overflow (reserve) responses

For overflow responses (`in_offer=False`), `manager_id` is still assigned via round robin. This preserves the assignment for future commission tracking regardless of whether the creator is in the main offer or reserve.

## Notification Flow

### Changes to `_send_contact_immediately()`

Add parameter `manager: Optional[User]`. Send order:
1. Advertiser — creator card (unchanged)
2. Manager — same `contact_text` + `open_profile_kb` via `send_with_retry()` (3 retries, 0.5s delay)
3. Creator — advertiser contacts (unchanged)

Manager receives the same content as advertiser. If no manager assigned — skip step 2.

**Edge case:** If a manager is removed from the order between assignment and notification, the notification still goes out (best-effort). The historical `manager_id` in `offer_dispatches` is preserved for commission tracking regardless of current `manager_orders` state.

## Admin Panel

### Custom field on Order edit form

In `OrderAdmin`:
1. Add `managers` via `form_extra_fields = {"managers": StringField("Менеджеры")}` — not mapped to a model column
2. On form open: use the existing custom `edit_template` (`order_edit.html`) with context injection (same pattern as `_inject_order_eligible_bloggers_count`). Load managers from `manager_orders`, resolve their telegram usernames, set field default to `@username1, @username2`
3. On save (`update_model()`):
   - Read `data.get("managers")`
   - Parse string: split by comma, strip whitespace, remove `@` prefix
   - For each username: validate via `user_repo.get_by_telegram(username)`
   - If not found: `raise ValueError(f"Пользователь с Telegram @{username} не найден в базе")`
   - Call `manager_service.set_managers_for_order(order_id, usernames)`
   - If empty string — delete all managers for the order

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
  Auth: validates user has records in manager_orders (returns only their orders)

POST /miniapp/api/manager/orders/{order_id}/creators
  Request: {init_data, in_offer: bool, limit: int, offset: int}
  Response: {creators: list[CreatorItem], total: int}
  Auth: validates current user is a manager for the given order
```

`CreatorItem`: `{instagram_url: str, telegram: str}`

## Testing

### Unit tests
- `ManagerService.set_managers_for_order()` — username validation, error on not found
- `ManagerService.get_next_manager_id()` — round robin (0→A, 1→B, 2→C, 3→A)
- `OfferResponseService.respond_and_finalize()` — verify `manager_id` written to `offer_dispatch`
- In-memory `MemoryManagerOrderRepository` in `infrastructure/memory_repositories.py`

### Integration tests
- Manager assignment via admin — save/load cycle
- Round robin with real DB
- Mini app endpoints with pagination

## Round Robin Algorithm

```
managers = sorted(list_by_order(order_id), key=lambda m: (m.created_at, m.user_id))
index = order.last_round_robin_index % len(managers)
selected_user_id = managers[index].user_id
order.last_round_robin_index += 1
```

Deterministic ordering by `(created_at, user_id)` ensures consistent rotation even when managers are added simultaneously.
