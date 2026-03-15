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
    """Manages manager-to-order assignments and round-robin routing."""

    manager_order_repo: ManagerOrderRepository
    user_repo: UserRepository
    order_repo: OrderRepository

    async def set_managers_for_order(
        self, order_id: UUID, telegram_usernames: list[str]
    ) -> None:
        """Replace managers for an order by Telegram username."""
        user_ids: list[UUID] = []
        for username in telegram_usernames:
            clean = username.strip().lstrip("@")
            if not clean:
                continue
            user = await self.user_repo.get_by_telegram(clean)
            if user is None:
                raise ValueError(
                    f"Пользователь с Telegram "
                    f"@{clean} не найден в базе"
                )
            user_ids.append(user.user_id)

        await self.manager_order_repo.delete_by_order(order_id)
        now = datetime.now(timezone.utc)
        for uid in user_ids:
            await self.manager_order_repo.save(
                ManagerOrder(
                    user_id=uid,
                    order_id=order_id,
                    created_at=now,
                    updated_at=now,
                )
            )

    async def get_next_manager_id(self, order: Order) -> Optional[UUID]:
        """Return next manager via round-robin, or None."""
        managers = await self.manager_order_repo.list_by_order(order.order_id)
        if not managers:
            return None
        return managers[order.last_round_robin_index % len(managers)].user_id

    async def is_manager(self, user_id: UUID) -> bool:
        """Check whether a user is assigned as manager to any order."""
        return await self.manager_order_repo.exists_for_user(user_id)

    async def list_orders_for_manager(
        self, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> tuple[list[Order], int]:
        """List orders assigned to a manager with pagination."""
        total = await self.manager_order_repo.count_by_user(user_id)
        order_ids = await self.manager_order_repo.list_order_ids_by_user(
            user_id, limit=limit, offset=offset
        )
        orders: list[Order] = []
        for oid in order_ids:
            order = await self.order_repo.get_by_id(oid)
            if order is not None:
                orders.append(order)
        return orders, total
