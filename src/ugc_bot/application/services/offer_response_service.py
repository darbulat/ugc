"""Service for handling offer responses."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.ports import OrderRepository, OrderResponseRepository
from ugc_bot.domain.entities import OrderResponse
from ugc_bot.domain.enums import OrderStatus


@dataclass(slots=True)
class OfferResponseService:
    """Handle blogger responses to offers."""

    order_repo: OrderRepository
    response_repo: OrderResponseRepository
    metrics_collector: Optional[Any] = None

    def respond(self, order_id: UUID, blogger_id: UUID) -> OrderResponse:
        """Create an order response if possible."""

        order = self.order_repo.get_by_id(order_id)
        if order is None:
            raise OrderCreationError("Order not found.")
        if order.status != OrderStatus.ACTIVE:
            raise OrderCreationError("Order is not active.")

        if self.response_repo.exists(order_id, blogger_id):
            raise OrderCreationError("You already responded to this order.")

        if self.response_repo.count_by_order(order_id) >= order.bloggers_needed:
            raise OrderCreationError("Order response limit reached.")

        response = OrderResponse(
            response_id=uuid4(),
            order_id=order_id,
            blogger_id=blogger_id,
            responded_at=datetime.now(timezone.utc),
        )
        self.response_repo.save(response)

        if self.metrics_collector:
            self.metrics_collector.record_blogger_response(
                order_id=str(order_id),
                blogger_id=str(blogger_id),
            )

        return response
