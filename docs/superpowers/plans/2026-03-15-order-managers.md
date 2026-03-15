# Order Managers Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manager assignment to orders with round-robin response routing, admin UI, and mini app for managers.

**Architecture:** Hexagonal (Ports & Adapters). New `ManagerOrder` entity + repository port + SQLAlchemy adapter + in-memory fake. `ManagerService` orchestrates logic. Changes to `OfferResponseService` for round-robin inside existing transaction. Mini app endpoints + HTML screens.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, aiogram, FastAPI, SQLAdmin, Pydantic, pytest

**Spec:** `docs/superpowers/specs/2026-03-15-order-managers-design.md`

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `src/ugc_bot/application/services/manager_service.py` | ManagerService: set managers, round robin, list orders |
| `src/ugc_bot/infrastructure/db/migrations/versions/0068_add_manager_orders.py` | Alembic migration |
| `tests/unit/test_manager_service.py` | Unit tests for ManagerService |
| `tests/unit/test_offer_response_with_managers.py` | Unit tests for round-robin in respond_and_finalize |
| `tests/integration/test_manager_miniapp.py` | Integration tests for mini app endpoints |

### Modified files
| File | Changes |
|------|---------|
| `src/ugc_bot/domain/entities.py` | Add `ManagerOrder` entity, `last_round_robin_index` to `Order`, `manager_id` to `OfferDispatch` |
| `src/ugc_bot/application/ports.py` | Add `ManagerOrderRepository` ABC, update `record_response` signature |
| `src/ugc_bot/infrastructure/db/models.py` | Add `ManagerOrderModel`, update `OrderModel`, `OfferDispatchModel` |
| `src/ugc_bot/infrastructure/db/repositories.py` | Add `SqlAlchemyManagerOrderRepository`, update `record_response`, add `list_responses_by_order_and_manager` |
| `src/ugc_bot/infrastructure/memory_repositories.py` | Add `InMemoryManagerOrderRepository`, update `InMemoryOfferDispatchRepository` |
| `src/ugc_bot/application/services/offer_response_service.py` | Add round-robin logic inside transaction, `manager_id` in result |
| `src/ugc_bot/bot/handlers/offer_responses.py` | Pass `manager` to `_send_contact_immediately`, send notification |
| `src/ugc_bot/admin/app.py` | Add `managers` field to `OrderAdmin`, validation in `update_model` |
| `src/ugc_bot/miniapp/api.py` | Add `is_manager` to `/me`, add manager endpoints |
| `src/ugc_bot/miniapp/app.html` | Add manager button, 3 new screens |
| `src/ugc_bot/container/repository_factory.py` | Register `SqlAlchemyManagerOrderRepository` |
| `src/ugc_bot/container/service_factory.py` | Build `ManagerService` |
| `src/ugc_bot/container/types.py` | Add `manager_service` and `manager_order_repo` to `BotServices` |
| `src/ugc_bot/container/__init__.py` | Add `build_manager_service` method |
| `tests/helpers/fakes.py` | Export `InMemoryManagerOrderRepository` if needed |

---

## Chunk 1: Domain + Ports + Infrastructure (Data Layer)

### Task 1: Domain entities

**Files:**
- Modify: `src/ugc_bot/domain/entities.py:167-234`

- [ ] **Step 1: Add `last_round_robin_index` to `Order` entity**

In `src/ugc_bot/domain/entities.py`, add after `currency: str = "RUB"` (line 213):

```python
    last_round_robin_index: int = 0
```

- [ ] **Step 2: Add `manager_id` to `OfferDispatch` entity**

In `src/ugc_bot/domain/entities.py`, add after `in_offer: bool` field (line 233):

```python
    manager_id: Optional[UUID] = None
```

- [ ] **Step 3: Add `ManagerOrder` entity**

In `src/ugc_bot/domain/entities.py`, add after the `OfferDispatch` class (after line 234):

```python
@dataclass(frozen=True)
class ManagerOrder:
    """Manager-to-order assignment for round-robin response routing."""

    user_id: UUID
    order_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None
```

- [ ] **Step 4: Run typecheck**

Run: `uv run mypy src/ugc_bot/domain/entities.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/domain/entities.py
git commit -m "feat: add ManagerOrder entity, last_round_robin_index to Order, manager_id to OfferDispatch"
```

---

### Task 2: Application ports

**Files:**
- Modify: `src/ugc_bot/application/ports.py`

- [ ] **Step 1: Update `record_response` signature**

In `OfferDispatchRepository`, update `record_response` to add `manager_id` parameter:

```python
    @abstractmethod
    async def record_response(
        self,
        order_id: UUID,
        blogger_id: UUID,
        accepted: bool,
        in_offer: bool,
        session: object | None = None,
        manager_id: UUID | None = None,
    ) -> None:
```

- [ ] **Step 2: Add `list_responses_by_order_and_manager` and `count_responses_by_order_and_manager`**

Add new abstract methods to `OfferDispatchRepository`:

```python
    @abstractmethod
    async def list_responses_by_order_and_manager(
        self,
        order_id: UUID,
        manager_id: UUID,
        in_offer: bool,
        limit: int = 20,
        offset: int = 0,
        session: object | None = None,
    ) -> list: ...

    @abstractmethod
    async def count_responses_by_order_and_manager(
        self,
        order_id: UUID,
        manager_id: UUID,
        in_offer: bool,
        session: object | None = None,
    ) -> int: ...
```

- [ ] **Step 3: Add `ManagerOrderRepository` ABC**

Add after `OfferDispatchRepository` class (imports: `from ugc_bot.domain.entities import ManagerOrder`):

```python
class ManagerOrderRepository(ABC):
    """Port for manager-order assignments."""

    @abstractmethod
    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> list: ...

    @abstractmethod
    async def list_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> list: ...

    @abstractmethod
    async def list_order_ids_by_user(
        self, user_id: UUID, limit: int = 20, offset: int = 0,
        session: object | None = None,
    ) -> list: ...

    @abstractmethod
    async def count_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> int: ...

    @abstractmethod
    async def save(
        self, manager_order: object, session: object | None = None
    ) -> None: ...

    @abstractmethod
    async def delete_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> None: ...

    @abstractmethod
    async def exists_for_user(
        self, user_id: UUID, session: object | None = None
    ) -> bool: ...
```

- [ ] **Step 4: Run typecheck**

Run: `uv run mypy src/ugc_bot/application/ports.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/application/ports.py
git commit -m "feat: add ManagerOrderRepository port, update record_response signature"
```

---

### Task 3: DB models

**Files:**
- Modify: `src/ugc_bot/infrastructure/db/models.py`

- [ ] **Step 1: Add `last_round_robin_index` to `OrderModel`**

Add column to `OrderModel` class:

```python
    last_round_robin_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
```

- [ ] **Step 2: Add `manager_id` to `OfferDispatchModel`**

Add column to `OfferDispatchModel`:

```python
    manager_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.user_id"), nullable=True
    )
```

- [ ] **Step 3: Add `ManagerOrderModel`**

Add new model class (after `OfferDispatchModel`):

```python
class ManagerOrderModel(Base):
    """Manager-to-order assignment."""

    __tablename__ = "manager_orders"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.order_id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 4: Run typecheck**

Run: `uv run mypy src/ugc_bot/infrastructure/db/models.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/infrastructure/db/models.py
git commit -m "feat: add ManagerOrderModel, last_round_robin_index, manager_id columns"
```

---

### Task 4: Alembic migration

**Files:**
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0068_add_manager_orders.py`

- [ ] **Step 1: Generate migration**

Run: `cd /home/bulat/PycharmProjects/ugc && uv run alembic revision --autogenerate -m "add_manager_orders"`

- [ ] **Step 2: Review and fix migration**

Verify the generated migration contains:
1. `op.create_table("manager_orders", ...)` with composite PK `(user_id, order_id)`
2. `op.add_column("orders", sa.Column("last_round_robin_index", sa.Integer(), server_default="0", nullable=False))`
3. `op.add_column("offer_dispatches", sa.Column("manager_id", sa.Uuid(), nullable=True))`
4. `op.create_foreign_key(None, "offer_dispatches", "users", ["manager_id"], ["user_id"])`

Rename file to `0068_add_manager_orders.py` if needed.

- [ ] **Step 3: Run migration**

Run: `uv run alembic upgrade head`
Expected: Migration applies successfully

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/infrastructure/db/migrations/versions/0068_*
git commit -m "feat: migration 0068 — manager_orders table, round robin index, manager_id"
```

---

### Task 5: SQLAlchemy repositories

**Files:**
- Modify: `src/ugc_bot/infrastructure/db/repositories.py`

- [ ] **Step 1: Update `record_response` to include `manager_id`**

In `SqlAlchemyOfferDispatchRepository.record_response()`, update signature and `.values()`:

```python
    async def record_response(
        self,
        order_id: UUID,
        blogger_id: UUID,
        accepted: bool,
        in_offer: bool,
        session: object | None = None,
        manager_id: UUID | None = None,
    ) -> None:
        db_session = _get_async_session(session)
        now = datetime.now(timezone.utc)
        await db_session.execute(
            update(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.blogger_id == blogger_id,
            )
            .values(
                accepted=accepted,
                in_offer=in_offer,
                updated_at=now,
                manager_id=manager_id,
            )
        )
```

- [ ] **Step 2: Add `list_responses_by_order_and_manager` and `count_responses_by_order_and_manager`**

```python
    async def list_responses_by_order_and_manager(
        self,
        order_id: UUID,
        manager_id: UUID,
        in_offer: bool,
        limit: int = 20,
        offset: int = 0,
        session: object | None = None,
    ) -> list[OfferDispatch]:
        db_session = _get_async_session(session) if session else self._new_session()
        async with self._session_scope(db_session, session is not None):
            stmt = (
                select(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.manager_id == manager_id,
                    OfferDispatchModel.in_offer == in_offer,
                    OfferDispatchModel.accepted == True,  # noqa: E712
                )
                .order_by(OfferDispatchModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await db_session.execute(stmt)
            return [self._to_entity(row) for row in result.scalars().all()]

    async def count_responses_by_order_and_manager(
        self,
        order_id: UUID,
        manager_id: UUID,
        in_offer: bool,
        session: object | None = None,
    ) -> int:
        db_session = _get_async_session(session) if session else self._new_session()
        async with self._session_scope(db_session, session is not None):
            stmt = (
                select(func.count())
                .select_from(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.manager_id == manager_id,
                    OfferDispatchModel.in_offer == in_offer,
                    OfferDispatchModel.accepted == True,  # noqa: E712
                )
            )
            result = await db_session.execute(stmt)
            return result.scalar() or 0
```

NOTE: Check existing patterns in the file for `_new_session()` / `_session_scope()` usage and follow them exactly.

- [ ] **Step 3: Update `_to_entity` for OfferDispatch**

Ensure the mapping includes `manager_id`:

```python
    manager_id=row.manager_id,
```

- [ ] **Step 4: Add `SqlAlchemyManagerOrderRepository`**

Add new repository class following existing patterns (`_new_session`, `_session_scope`, `_to_entity`). Methods: `list_by_order`, `list_by_user`, `list_order_ids_by_user`, `count_by_user`, `save`, `delete_by_order`, `exists_for_user`. Use `ManagerOrderModel` for queries, return `ManagerOrder` entities. Sort `list_by_order` by `(created_at, user_id)` for deterministic round-robin.

- [ ] **Step 5: Update Order entity mapping**

Find where `OrderModel` to `Order` entity mapping happens in repositories.py. Add `last_round_robin_index=row.last_round_robin_index` to the mapping.

- [ ] **Step 6: Update OfferDispatch entity mapping**

Find where `OfferDispatchModel` to `OfferDispatch` entity mapping happens. Add `manager_id=row.manager_id`.

- [ ] **Step 7: Run typecheck**

Run: `uv run mypy src/ugc_bot/infrastructure/db/repositories.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/ugc_bot/infrastructure/db/repositories.py
git commit -m "feat: add SqlAlchemyManagerOrderRepository, update record_response and mappings"
```

---

### Task 6: In-memory repositories

**Files:**
- Modify: `src/ugc_bot/infrastructure/memory_repositories.py`

- [ ] **Step 1: Update `InMemoryOfferDispatchRepository.record_response`**

Add `manager_id` parameter to `record_response()` and include it in the `replace()` call.

- [ ] **Step 2: Add `list_responses_by_order_and_manager` and `count_responses_by_order_and_manager`**

Filter by `order_id`, `manager_id`, `in_offer`, and `accepted is True`. Support `limit`/`offset`.

- [ ] **Step 3: Add `InMemoryManagerOrderRepository`**

Keyed by `(user_id, order_id)` tuple. Implement all methods from `ManagerOrderRepository`. Sort `list_by_order` by `(created_at, user_id)`.

- [ ] **Step 4: Run typecheck**

Run: `uv run mypy src/ugc_bot/infrastructure/memory_repositories.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/infrastructure/memory_repositories.py
git commit -m "feat: add InMemoryManagerOrderRepository, update record_response"
```

---

### Task 7: Container wiring

**Files:**
- Modify: `src/ugc_bot/container/repository_factory.py`
- Modify: `src/ugc_bot/container/service_factory.py`
- Modify: `src/ugc_bot/container/types.py`
- Modify: `src/ugc_bot/container/__init__.py`

- [ ] **Step 1: Register repo in `repository_factory.py`**

Add import of `SqlAlchemyManagerOrderRepository` and add to dict:

```python
        "manager_order_repo": SqlAlchemyManagerOrderRepository(
            session_factory=session_factory
        ),
```

- [ ] **Step 2: Add `ManagerService` to `service_factory.py`**

Add import and build function. In `build_bot_services()`, add to the returned dict:

```python
        "manager_service": ManagerService(
            manager_order_repo=repos["manager_order_repo"],
            user_repo=repos["user_repo"],
            order_repo=repos["order_repo"],
        ),
        "manager_order_repo": repos["manager_order_repo"],
```

- [ ] **Step 3: Update `BotServices` in `types.py`**

Add `ManagerService` import and fields:

```python
    manager_service: ManagerService
    manager_order_repo: Any
```

- [ ] **Step 4: Add `build_manager_service` to Container**

In `src/ugc_bot/container/__init__.py`, add method:

```python
    def build_manager_service(self) -> ManagerService:
        """ManagerService for admin panel."""
        repos = self.build_repos()
        return ManagerService(
            manager_order_repo=repos["manager_order_repo"],
            user_repo=repos["user_repo"],
            order_repo=repos["order_repo"],
        )
```

- [ ] **Step 5: Run typecheck**

Run: `uv run mypy src/ugc_bot/container/`
Expected: PASS (will fail until ManagerService exists — that is Task 9)

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/container/
git commit -m "feat: wire ManagerService and ManagerOrderRepository in container"
```

---

## Chunk 2: ManagerService + Round Robin in OfferResponseService

### Task 8: Unit tests for ManagerService

**Files:**
- Create: `tests/unit/test_manager_service.py`

- [ ] **Step 1: Write tests**

Tests to cover:
- `set_managers_for_order` success with valid usernames
- `set_managers_for_order` raises `ValueError` when username not found
- `set_managers_for_order` replaces existing managers
- `get_next_manager_id` round robin: index 0 to A, 1 to B, 2 to C, 3 to A again
- `get_next_manager_id` returns None when no managers
- `is_manager` returns False/True correctly

Use `InMemoryManagerOrderRepository`, `InMemoryUserRepository`, `InMemoryOrderRepository`. Create helper `_make_user(telegram=...)` and `_make_order()` factories matching entity constructors.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manager_service.py -v`
Expected: FAIL — `ManagerService` does not exist yet

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_manager_service.py
git commit -m "test: add unit tests for ManagerService"
```

---

### Task 9: Implement ManagerService

**Files:**
- Create: `src/ugc_bot/application/services/manager_service.py`

- [ ] **Step 1: Write ManagerService**

```python
"""Service for managing manager-to-order assignments."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from ugc_bot.application.ports import (
    ManagerOrderRepository,
    OrderRepository,
    UserRepository,
)
from ugc_bot.domain.entities import ManagerOrder, Order


@dataclass(slots=True)
class ManagerService:
    """Manage manager-order assignments and round-robin selection."""

    manager_order_repo: ManagerOrderRepository
    user_repo: UserRepository
    order_repo: OrderRepository

    async def set_managers_for_order(
        self, order_id: UUID, telegram_usernames: list[str]
    ) -> None:
        user_ids: list[UUID] = []
        for username in telegram_usernames:
            clean = username.strip().lstrip("@")
            if not clean:
                continue
            user = await self.user_repo.get_by_telegram(clean)
            if user is None:
                raise ValueError(
                    f"Пользователь с Telegram @{clean} не найден в базе"
                )
            user_ids.append(user.user_id)

        await self.manager_order_repo.delete_by_order(order_id)
        now = datetime.now(timezone.utc)
        for uid in user_ids:
            await self.manager_order_repo.save(
                ManagerOrder(
                    user_id=uid, order_id=order_id,
                    created_at=now, updated_at=now,
                )
            )

    async def get_next_manager_id(self, order: Order) -> Optional[UUID]:
        managers = await self.manager_order_repo.list_by_order(order.order_id)
        if not managers:
            return None
        index = order.last_round_robin_index % len(managers)
        return managers[index].user_id

    async def is_manager(self, user_id: UUID) -> bool:
        return await self.manager_order_repo.exists_for_user(user_id)

    async def list_orders_for_manager(
        self, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> tuple[list[Order], int]:
        total = await self.manager_order_repo.count_by_user(user_id)
        order_ids = await self.manager_order_repo.list_order_ids_by_user(
            user_id, limit=limit, offset=offset
        )
        orders = []
        for oid in order_ids:
            order = await self.order_repo.get_by_id(oid)
            if order is not None:
                orders.append(order)
        return orders, total
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/unit/test_manager_service.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/application/services/manager_service.py
git commit -m "feat: implement ManagerService"
```

---

### Task 10: Unit tests for round robin in OfferResponseService

**Files:**
- Create: `tests/unit/test_offer_response_with_managers.py`

- [ ] **Step 1: Write tests**

Tests to cover:
1. When managers exist, `respond_and_finalize` assigns `manager_id` and increments `last_round_robin_index`
2. When no managers exist, `manager_id` is None
3. Two consecutive responses get different managers (round robin)

Use in-memory repos. `OfferResponseService` will need `manager_order_repo` as new optional parameter. Check how existing tests handle `transaction_manager=None`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_offer_response_with_managers.py -v`
Expected: FAIL — `manager_order_repo` not accepted

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_offer_response_with_managers.py
git commit -m "test: add unit tests for round-robin manager assignment"
```

---

### Task 11: Update OfferResponseService

**Files:**
- Modify: `src/ugc_bot/application/services/offer_response_service.py`
- Modify: `src/ugc_bot/container/service_factory.py`

- [ ] **Step 1: Add `manager_order_repo` dependency**

Add `ManagerOrderRepository` import and field:

```python
    manager_order_repo: ManagerOrderRepository | None = None
```

- [ ] **Step 2: Add `manager_id` to `OfferResponseResult`**

```python
    manager_id: UUID | None = None
```

- [ ] **Step 3: Add round-robin logic inside transaction**

Inside the `respond_and_finalize` transaction block, BEFORE `record_response`:

1. Select manager via round robin from `manager_order_repo.list_by_order`
2. Compute `manager_id`
3. Pass `manager_id` to `record_response`
4. After order update, also increment `last_round_robin_index` via `dataclasses.replace`
5. Save the updated order

Correct order inside transaction:
1. Get `accepted_count`, compute `within_limit`
2. Select manager (read `manager_order_repo.list_by_order`)
3. Call `record_response` with `manager_id`
4. Update order (response count + round robin index) and save

- [ ] **Step 4: Update `OfferResponseResult` construction**

Include `manager_id` in the returned result and in the `OfferDispatch` construction.

- [ ] **Step 5: Update service construction in `service_factory.py`**

In `build_bot_services()`, add `manager_order_repo` to `offer_response_service`:

```python
        "offer_response_service": OfferResponseService(
            order_repo=repos["order_repo"],
            dispatch_repo=repos["offer_dispatch_repo"],
            manager_order_repo=repos["manager_order_repo"],
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
        ),
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/unit/test_offer_response_with_managers.py tests/unit/test_manager_service.py -v`
Expected: PASS

- [ ] **Step 7: Run full unit test suite**

Run: `uv run pytest tests/unit/ -v --timeout=5`
Expected: PASS — no regressions

- [ ] **Step 8: Commit**

```bash
git add src/ugc_bot/application/services/offer_response_service.py src/ugc_bot/container/service_factory.py
git commit -m "feat: add round-robin manager assignment to OfferResponseService"
```

---

## Chunk 3: Notification + Admin + Mini App

### Task 12: Manager notification in bot handler

**Files:**
- Modify: `src/ugc_bot/bot/handlers/offer_responses.py`

- [ ] **Step 1: Add `manager` parameter to `_send_contact_immediately`**

Add `manager: User | None = None` to the function signature (line 402).

- [ ] **Step 2: Add manager notification after advertiser notification**

After the advertiser notification block (after line ~465), add `send_with_retry` call to `manager.external_id` with the same `contact_text` and `open_profile_kb`.

- [ ] **Step 3: Update the call site**

Where `_send_contact_immediately` is called (around line 147), resolve manager from `result.manager_id`:

```python
        manager = None
        if result.manager_id:
            manager = await user_role_service.get_user_by_id(result.manager_id)
```

Pass `manager=manager` to the function call.

- [ ] **Step 4: Run typecheck**

Run: `uv run mypy src/ugc_bot/bot/handlers/offer_responses.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/bot/handlers/offer_responses.py
git commit -m "feat: send creator card to assigned manager on response"
```

---

### Task 13: Admin panel — managers field on Order form

**Files:**
- Modify: `src/ugc_bot/admin/app.py`

- [ ] **Step 1: Add managers field to OrderAdmin**

Add `form_extra_fields` with `StringField("Managers")`. Add `"managers"` to `form_columns`.

- [ ] **Step 2: Pre-populate managers field on edit**

Add context injection function similar to `_inject_order_eligible_bloggers_count`. Load managers from `manager_order_repo`, resolve telegram usernames, set field data. Call it in `EnumAwareAdmin.edit()`.

- [ ] **Step 3: Handle save in `OrderAdmin.update_model`**

Pop `"managers"` from `data` before `super().update_model()`. Parse comma-separated usernames. Call `manager_service.set_managers_for_order()`. Handle empty string by deleting all managers.

- [ ] **Step 4: Run typecheck**

Run: `uv run mypy src/ugc_bot/admin/app.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/admin/app.py
git commit -m "feat: add managers field to OrderAdmin with validation"
```

---

### Task 14: Mini app API endpoints

**Files:**
- Modify: `src/ugc_bot/miniapp/api.py`

- [ ] **Step 1: Add `is_manager` to MeResponse**

Add `is_manager: bool = False` field. In `/me` handler, resolve via `manager_service.is_manager(user_id)`.

- [ ] **Step 2: Add Pydantic request/response models**

`ManagerOrdersRequest`, `ManagerOrdersResponse`, `ManagerCreatorsRequest`, `CreatorItem`, `ManagerCreatorsResponse`.

- [ ] **Step 3: Add `POST /manager/orders` endpoint**

Get user_id from init_data. Call `manager_service.list_orders_for_manager()`. Return paginated response.

- [ ] **Step 4: Add `POST /manager/orders/{order_id}/creators` endpoint**

Verify user is manager for order. Call `dispatch_repo.list_responses_by_order_and_manager()`. Resolve creator instagram_url and telegram. Return paginated response.

- [ ] **Step 5: Wire services in app startup**

Ensure `manager_service`, `manager_order_repo` are available on `app.state` (follow existing pattern from `telegram_webhook_app.py`).

- [ ] **Step 6: Run typecheck**

Run: `uv run mypy src/ugc_bot/miniapp/api.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/miniapp/api.py
git commit -m "feat: add manager endpoints to mini app API"
```

---

### Task 15: Mini app HTML screens

**Files:**
- Modify: `src/ugc_bot/miniapp/app.html`

- [ ] **Step 1: Add manager button to role choice screen**

Add hidden button `data-role="manager"` in `screen-role-choice`. Show via JS when `me.is_manager` is true.

- [ ] **Step 2: Add manager screens HTML**

Three screens: `screen-manager-orders` (paginated order list), `screen-manager-order-detail` (two buttons: in offer / reserve), `screen-manager-creators` (paginated creator list with instagram and telegram links).

- [ ] **Step 3: Add JavaScript logic**

Functions: `loadManagerOrders(offset)`, `openManagerOrder(orderId, title)`, `loadManagerCreators(orderId, inOffer, offset)`. Pagination handlers for prev/next buttons. Use `textContent` for plain text and safe DOM methods for building list items — avoid setting raw HTML from API data to prevent XSS.

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/miniapp/app.html
git commit -m "feat: add manager screens to mini app"
```

---

### Task 16: Final checks

- [ ] **Step 1: Run format + lint**

Run: `make format && make lint`
Expected: PASS

- [ ] **Step 2: Run typecheck**

Run: `make typecheck`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `make test`
Expected: PASS

- [ ] **Step 4: Run coverage**

Run: `make coverage`
Expected: PASS (at least 98%)

- [ ] **Step 5: Run `make fix`**

Run: `make fix`
Expected: All checks pass

- [ ] **Step 6: Final commit if any formatting changes**

```bash
git add -u
git commit -m "chore: format and lint fixes"
```
