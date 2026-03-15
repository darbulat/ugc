"""Service for managing manager-to-order assignments."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from ugc_bot.application.errors import ManagerUserNotFoundError
from ugc_bot.application.ports import (
    ManagerOrderRepository,
    OfferDispatchRepository,
    OrderRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import ManagerOrder, OfferDispatch, Order
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class ManagerService:
    """Manages manager-to-order assignments and round-robin routing."""

    manager_order_repo: ManagerOrderRepository
    user_repo: UserRepository
    order_repo: OrderRepository
    offer_dispatch_repo: OfferDispatchRepository | None = None
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
                    raise ManagerUserNotFoundError(clean)
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
            orders = await self.order_repo.get_by_ids(
                order_ids, session=session
            )
            return orders, total

        return await with_optional_tx(self.transaction_manager, _run)

    async def is_manager_for_order(self, user_id: UUID, order_id: UUID) -> bool:
        """Check whether user is a manager for a specific order."""

        async def _run(session: object | None) -> bool:
            managers = await self.manager_order_repo.list_by_order(
                order_id, session=session
            )
            return any(m.user_id == user_id for m in managers)

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_creators_for_order(
        self,
        order_id: UUID,
        manager_id: UUID,
        in_offer: bool,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[OfferDispatch], int]:
        """List creator dispatches for an order visible to a manager.

        For in_offer=True returns only dispatches assigned to *manager_id*.
        For in_offer=False (reserve) returns all dispatches for the order.
        """
        if self.offer_dispatch_repo is None:
            return [], 0

        repo = self.offer_dispatch_repo

        async def _run(
            session: object | None,
        ) -> tuple[list[OfferDispatch], int]:
            effective_manager_id = manager_id if in_offer else None
            dispatches = await repo.list_responses_by_order_and_manager(
                order_id=order_id,
                manager_id=effective_manager_id,
                in_offer=in_offer,
                limit=limit,
                offset=offset,
                session=session,
            )
            total = await repo.count_responses_by_order_and_manager(
                order_id=order_id,
                manager_id=effective_manager_id,
                in_offer=in_offer,
                session=session,
            )
            return dispatches, total

        return await with_optional_tx(self.transaction_manager, _run)
