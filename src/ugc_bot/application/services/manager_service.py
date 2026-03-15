"""Service for managing manager-to-order assignments."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from ugc_bot.application.ports import (
    ManagerOrderRepository,
    OrderRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import ManagerOrder, Order
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class ManagerService:
    """Manages manager-to-order assignments and round-robin routing."""

    manager_order_repo: ManagerOrderRepository
    user_repo: UserRepository
    order_repo: OrderRepository
    transaction_manager: TransactionManager | None = None

    async def set_managers_for_order(
        self, order_id: UUID, telegram_usernames: list[str]
    ) -> None:
        """Replace managers for an order by Telegram username."""

        async def _run(session: object | None) -> None:
            user_ids: list[UUID] = []
            for username in telegram_usernames:
                clean = username.strip().lstrip("@")
                if not clean:
                    continue
                user = await self.user_repo.get_by_telegram(
                    clean, session=session
                )
                if user is None:
                    raise ValueError(
                        f"Пользователь с Telegram @{clean} не найден в базе"
                    )
                user_ids.append(user.user_id)

            await self.manager_order_repo.delete_by_order(
                order_id, session=session
            )
            now = datetime.now(timezone.utc)
            for uid in user_ids:
                await self.manager_order_repo.save(
                    ManagerOrder(
                        user_id=uid,
                        order_id=order_id,
                        created_at=now,
                        updated_at=now,
                    ),
                    session=session,
                )

        await with_optional_tx(self.transaction_manager, _run)

    async def get_next_manager_id(self, order: Order) -> Optional[UUID]:
        """Return next manager via round-robin, or None."""

        async def _run(session: object | None) -> Optional[UUID]:
            managers = await self.manager_order_repo.list_by_order(
                order.order_id, session=session
            )
            if not managers:
                return None
            return managers[
                order.last_round_robin_index % len(managers)
            ].user_id

        return await with_optional_tx(self.transaction_manager, _run)

    async def is_manager(self, user_id: UUID) -> bool:
        """Check whether a user is assigned as manager to any order."""

        async def _run(session: object | None) -> bool:
            return await self.manager_order_repo.exists_for_user(
                user_id, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_orders_for_manager(
        self, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> tuple[list[Order], int]:
        """List orders assigned to a manager with pagination."""

        async def _run(
            session: object | None,
        ) -> tuple[list[Order], int]:
            total = await self.manager_order_repo.count_by_user(
                user_id, session=session
            )
            order_ids = await self.manager_order_repo.list_order_ids_by_user(
                user_id,
                limit=limit,
                offset=offset,
                session=session,
            )
            orders: list[Order] = []
            for oid in order_ids:
                order = await self.order_repo.get_by_id(oid, session=session)
                if order is not None:
                    orders.append(order)
            return orders, total

        return await with_optional_tx(self.transaction_manager, _run)
