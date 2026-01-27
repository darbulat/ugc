"""Service for handling offer responses."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncContextManager, Optional, Protocol
from uuid import UUID, uuid4

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.ports import OrderRepository, OrderResponseRepository
from ugc_bot.domain.entities import Order, OrderResponse
from ugc_bot.domain.enums import OrderStatus


class TransactionManager(Protocol):
    """Protocol for database transaction handling."""

    def transaction(self) -> AsyncContextManager[Any]:
        """Return a context manager for a transaction."""


@dataclass(slots=True)
class OfferResponseResult:
    """Result of a successful offer response flow."""

    order: Order
    response: OrderResponse
    response_count: int
    order_closed: bool
    contacts_sent_at: datetime


@dataclass(slots=True)
class OfferResponseService:
    """Handle blogger responses to offers."""

    order_repo: OrderRepository
    response_repo: OrderResponseRepository
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def respond(self, order_id: UUID, blogger_id: UUID) -> OrderResponse:
        """Create an order response if possible."""

        result = await self.respond_and_finalize(order_id, blogger_id)
        return result.response

    async def respond_and_finalize(
        self, order_id: UUID, blogger_id: UUID
    ) -> OfferResponseResult:
        """Create response and update order in a single flow."""

        now = datetime.now(timezone.utc)
        if self.transaction_manager is None:
            order = await self.order_repo.get_by_id(order_id)
            if order is None:
                raise OrderCreationError("Order not found.")
            if order.status != OrderStatus.ACTIVE:
                raise OrderCreationError("Order is not active.")
            if await self.response_repo.exists(order_id, blogger_id):
                raise OrderCreationError("You already responded to this order.")

            response_count = await self.response_repo.count_by_order(order_id)
            if response_count >= order.bloggers_needed:
                raise OrderCreationError("Order response limit reached.")

            response = OrderResponse(
                response_id=uuid4(),
                order_id=order_id,
                blogger_id=blogger_id,
                responded_at=now,
            )
            await self.response_repo.save(response)
            response_count += 1
            updated = _update_order_after_response(order, response_count, now=now)
            await self.order_repo.save(updated)
        else:
            async with self.transaction_manager.transaction() as session:
                order = await self.order_repo.get_by_id_for_update(
                    order_id, session=session
                )
                if order is None:
                    raise OrderCreationError("Order not found.")
                if order.status != OrderStatus.ACTIVE:
                    raise OrderCreationError("Order is not active.")
                if await self.response_repo.exists(
                    order_id, blogger_id, session=session
                ):
                    raise OrderCreationError("You already responded to this order.")

                response_count = await self.response_repo.count_by_order(
                    order_id, session=session
                )
                if response_count >= order.bloggers_needed:
                    raise OrderCreationError("Order response limit reached.")

                response = OrderResponse(
                    response_id=uuid4(),
                    order_id=order_id,
                    blogger_id=blogger_id,
                    responded_at=now,
                )
                await self.response_repo.save(response, session=session)
                response_count += 1
                updated = _update_order_after_response(order, response_count, now=now)
                await self.order_repo.save(updated, session=session)

        if self.metrics_collector:
            self.metrics_collector.record_blogger_response(
                order_id=str(order_id),
                blogger_id=str(blogger_id),
            )

        order_closed = updated.status == OrderStatus.CLOSED
        return OfferResponseResult(
            order=updated,
            response=response,
            response_count=response_count,
            order_closed=order_closed,
            contacts_sent_at=now,
        )


def _update_order_after_response(
    order: Order, response_count: int, now: datetime
) -> Order:
    """Return updated order after a response is accepted."""

    new_status = (
        OrderStatus.CLOSED if response_count >= order.bloggers_needed else order.status
    )
    return Order(
        order_id=order.order_id,
        advertiser_id=order.advertiser_id,
        product_link=order.product_link,
        offer_text=order.offer_text,
        ugc_requirements=order.ugc_requirements,
        barter_description=order.barter_description,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=new_status,
        created_at=order.created_at,
        contacts_sent_at=now,
    )
