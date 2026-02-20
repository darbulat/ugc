"""Service for handling offer responses."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.ports import (
    OfferDispatchRepository,
    OrderRepository,
    TransactionManager,
)
from ugc_bot.domain.entities import OfferDispatch, Order
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class OfferResponseResult:
    """Result of a successful offer response flow."""

    order: Order
    response: OfferDispatch
    response_count: int
    order_closed: bool
    completed_at: Optional[datetime]
    accepted: bool  # True = within limit; False = overflow (analytics/reserve)


@dataclass(slots=True)
class OfferResponseService:
    """Handle blogger responses to offers."""

    order_repo: OrderRepository
    dispatch_repo: OfferDispatchRepository
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def respond(self, order_id: UUID, blogger_id: UUID) -> OfferDispatch:
        """Record response and return the updated dispatch."""

        result = await self.respond_and_finalize(order_id, blogger_id)
        return result.response

    async def list_by_order(self, order_id: UUID) -> list[OfferDispatch]:
        """List dispatches (responses) for an order within a transaction."""

        async def _run(session: object | None):
            return list(
                await self.dispatch_repo.list_responses_by_order(
                    order_id, session=session
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_by_blogger(self, blogger_id: UUID) -> list[OfferDispatch]:
        """List dispatches where blogger responded (accepted is not null)."""

        async def _run(session: object | None):
            return list(
                await self.dispatch_repo.list_responses_by_blogger(
                    blogger_id, session=session
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def count_by_order(self, order_id: UUID) -> int:
        """Count dispatches for an order."""

        async def _run(session: object | None):
            return await self.dispatch_repo.count_by_order(
                order_id, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def respond_and_finalize(
        self, order_id: UUID, blogger_id: UUID
    ) -> OfferResponseResult:
        """Record response (accepted/in_offer) and update order in one tx."""

        if self.transaction_manager is None:
            raise ValueError(
                "OfferResponseService needs transaction_manager for atomic ops."
            )

        now = datetime.now(timezone.utc)
        async with self.transaction_manager.transaction() as session:
            order = await self.order_repo.get_by_id_for_update(
                order_id, session=session
            )
            if order is None:
                raise OrderCreationError("Order not found.")
            accepted_count = await self.dispatch_repo.count_accepted_by_order(
                order_id, session=session
            )
            order_closed_or_inactive = order.status != OrderStatus.ACTIVE
            if (
                order_closed_or_inactive
                and accepted_count < order.bloggers_needed
            ):
                raise OrderCreationError("Order is not active.")
            if await self.dispatch_repo.exists_responded(
                order_id, blogger_id, session=session
            ):
                raise OrderCreationError("You already responded to this order.")

            within_limit = accepted_count < order.bloggers_needed
            await self.dispatch_repo.record_response(
                order_id,
                blogger_id,
                accepted=True,
                in_offer=within_limit,
                session=session,
            )

            if within_limit:
                response_count = accepted_count + 1
                updated = _update_order_after_response(
                    order, response_count, now=now
                )
                await self.order_repo.save(updated, session=session)
            else:
                updated = order
                response_count = accepted_count

        if self.metrics_collector:
            self.metrics_collector.record_blogger_response(
                order_id=str(order_id),
                blogger_id=str(blogger_id),
            )

        order_closed = updated.status == OrderStatus.CLOSED
        response = OfferDispatch(
            order_id=order_id,
            blogger_id=blogger_id,
            created_at=now,
            updated_at=now,
            accepted=True,
            in_offer=within_limit,
        )
        return OfferResponseResult(
            order=updated,
            response=response,
            response_count=response_count,
            order_closed=order_closed,
            completed_at=updated.completed_at,
            accepted=within_limit,
        )


def _update_order_after_response(
    order: Order, response_count: int, now: datetime
) -> Order:
    """Return updated order after a response is accepted."""

    new_status = (
        OrderStatus.CLOSED
        if response_count >= order.bloggers_needed
        else order.status
    )
    completed_at = (
        now if response_count >= order.bloggers_needed else order.completed_at
    )
    return replace(
        order,
        status=new_status,
        completed_at=completed_at,
        updated_at=now,
    )
