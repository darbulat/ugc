"""Service for managing manager-to-order assignments."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
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

logger = logging.getLogger(__name__)


@asynccontextmanager
async def manager_creator_mutation(
    manager_service: "ManagerService",
    order_repo: OrderRepository,
    repo: OfferDispatchRepository | None,
    transaction_manager: TransactionManager | None,
    order_id: UUID,
    blogger_id: UUID,
    manager_id: UUID,
    *,
    is_admin: bool = False,
    allow_reserve: bool = False,
) -> AsyncIterator[tuple[Order, OfferDispatch, object | None]]:
    """Authorize the current pair while retaining order/pair write locks.

    Order first matches offer acceptance lock order and serializes slot checks
    and manager-list replacement. SQL adapters reject a lock without a session.
    """
    if repo is None:
        raise LookupError("Creator assignment repository is unavailable")

    async def locked(session: object | None) -> tuple[Order, OfferDispatch]:
        order = await order_repo.get_by_id(
            order_id, session=session, for_update=True
        )
        if order is None:
            raise LookupError("Order not found")
        dispatch = await repo.get_by_order_and_blogger(
            order_id, blogger_id, session=session, for_update=True
        )
        if dispatch is None:
            raise LookupError("Creator not found in this order")
        if not isinstance(manager_id, UUID):
            raise PermissionError("Invalid authenticated identity")
        if not is_admin and (
            not await manager_service.is_manager_for_order(
                manager_id, order_id, session=session
            )
            or not ManagerService.is_assigned_to_creator(
                manager_id,
                order_id,
                blogger_id,
                dispatch,
                allow_reserve=allow_reserve,
            )
        ):
            raise PermissionError("Not assigned to this creator")
        return order, dispatch

    if transaction_manager is None:
        order, dispatch = await locked(None)
        yield order, dispatch, None
    else:
        async with transaction_manager.transaction() as session:
            order, dispatch = await locked(session)
            yield order, dispatch, session
    if is_admin:
        logger.info(
            "Admin manager-pair mutation committed",
            extra={
                "event": "admin_manager_pair_mutation",
                "user_id": str(manager_id),
                "order_id": str(order_id),
                "blogger_id": str(blogger_id),
                "previous_manager_id": str(dispatch.manager_id),
            },
        )


@dataclass(slots=True)
class ManagerService:
    """Manages manager-to-order assignments and round-robin routing."""

    manager_order_repo: ManagerOrderRepository
    user_repo: UserRepository
    order_repo: OrderRepository
    offer_dispatch_repo: OfferDispatchRepository | None = None
    transaction_manager: TransactionManager | None = None

    @staticmethod
    def is_assigned_to_creator(
        user_id: UUID,
        order_id: UUID,
        blogger_id: UUID,
        dispatch: OfferDispatch,
        *,
        allow_reserve: bool = False,
    ) -> bool:
        """Match the authenticated manager to this exact assignment."""
        return (
            isinstance(user_id, UUID)
            and dispatch.order_id == order_id
            and dispatch.blogger_id == blogger_id
            and dispatch.manager_id == user_id
            and (dispatch.in_offer or allow_reserve)
        )

    async def assign_returning_creator(
        self,
        order_id: UUID,
        blogger_id: UUID,
        manager_id: UUID,
        *,
        is_admin: bool = False,
    ) -> OfferDispatch:
        """Commit a reserve return and return the saved assignment snapshot."""
        repo = self.offer_dispatch_repo
        if repo is None:
            raise LookupError("Creator assignment repository is unavailable")

        async with manager_creator_mutation(
            self,
            self.order_repo,
            repo,
            self.transaction_manager,
            order_id,
            blogger_id,
            manager_id,
            is_admin=is_admin,
            allow_reserve=True,
        ) as (order, dispatch, session):
            if dispatch.in_offer:
                raise ValueError("Creator is already in the order")
            if (
                await repo.count_accepted_by_order(order_id, session=session)
                >= order.bloggers_needed
            ):
                raise ValueError("No free slots in this order")
            await repo.set_in_offer(order_id, blogger_id, True, session=session)
            await repo.set_manager(
                order_id, blogger_id, manager_id, session=session
            )
        return replace(dispatch, in_offer=True, manager_id=manager_id)

    async def set_managers_for_order(
        self, order_id: UUID, telegram_usernames: list[str]
    ) -> None:
        """Replace managers for an order by Telegram username."""

        async def _run(session: object | None) -> None:
            await self.order_repo.get_by_id(
                order_id, session=session, for_update=True
            )
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

    async def list_all_orders(
        self, limit: int = 20, offset: int = 0
    ) -> tuple[list[Order], int]:
        """List all orders with pagination (for admin users)."""

        async def _run(
            session: object | None,
        ) -> tuple[list[Order], int]:
            total = await self.order_repo.count_all(session=session)
            orders = await self.order_repo.list_all_paginated(
                limit=limit, offset=offset, session=session
            )
            return orders, total

        return await with_optional_tx(self.transaction_manager, _run)

    async def is_manager_for_order(
        self, user_id: UUID, order_id: UUID, *, session: object | None = None
    ) -> bool:
        """Check whether user is a manager for a specific order."""

        async def _run(session: object | None) -> bool:
            managers = await self.manager_order_repo.list_by_order(
                order_id, session=session
            )
            return any(m.user_id == user_id for m in managers)

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)

    async def list_creators_for_order(
        self,
        order_id: UUID,
        manager_id: Optional[UUID],
        in_offer: bool,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[OfferDispatch], int]:
        """List creator dispatches for an order visible to a manager.

        For in_offer=True returns only dispatches assigned to *manager_id*
        (or all if manager_id is None, e.g. for admin users).
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

    async def list_expensive_creators(
        self,
        order_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[OfferDispatch], int]:
        """List creators who declined due to low price."""
        if self.offer_dispatch_repo is None:
            return [], 0

        repo = self.offer_dispatch_repo

        async def _run(
            session: object | None,
        ) -> tuple[list[OfferDispatch], int]:
            dispatches = await repo.list_by_order_and_rejection_reason(
                order_id=order_id,
                rejection_reason="low_price",
                limit=limit,
                offset=offset,
                session=session,
            )
            total = await repo.count_by_order_and_rejection_reason(
                order_id=order_id,
                rejection_reason="low_price",
                session=session,
            )
            return dispatches, total

        return await with_optional_tx(self.transaction_manager, _run)
