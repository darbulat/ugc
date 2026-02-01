"""Service for order creation and validation."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    OrderRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus, OrderType, UserStatus

logger = logging.getLogger(__name__)


_ALLOWED_BLOGGER_COUNTS = {3, 5, 10}


@dataclass(slots=True)
class OrderService:
    """Create advertiser orders with validation."""

    user_repo: UserRepository
    advertiser_repo: AdvertiserProfileRepository
    order_repo: OrderRepository
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def is_new_advertiser(self, advertiser_id: UUID) -> bool:
        """Return True when advertiser has no previous orders."""

        if self.transaction_manager is None:
            return await self.order_repo.count_by_advertiser(advertiser_id) == 0
        async with self.transaction_manager.transaction() as session:
            return (
                await self.order_repo.count_by_advertiser(
                    advertiser_id, session=session
                )
                == 0
            )

    async def list_by_advertiser(self, advertiser_id: UUID) -> list[Order]:
        """List orders for advertiser."""

        if self.transaction_manager is None:
            return list(await self.order_repo.list_by_advertiser(advertiser_id))
        async with self.transaction_manager.transaction() as session:
            return list(
                await self.order_repo.list_by_advertiser(advertiser_id, session=session)
            )

    async def get_order(self, order_id: UUID) -> Order | None:
        """Fetch order by id within a transaction boundary."""

        if self.transaction_manager is None:
            return await self.order_repo.get_by_id(order_id)
        async with self.transaction_manager.transaction() as session:
            return await self.order_repo.get_by_id(order_id, session=session)

    async def create_order(
        self,
        advertiser_id: UUID,
        order_type: OrderType,
        product_link: str,
        offer_text: str,
        ugc_requirements: Optional[str],
        barter_description: Optional[str],
        price: float,
        bloggers_needed: int,
    ) -> Order:
        """Create an order after validating input."""

        if self.transaction_manager is None:
            user = await self.user_repo.get_by_id(advertiser_id)
            if user is None:
                raise UserNotFoundError("Advertiser not found.")

            advertiser_profile = await self.advertiser_repo.get_by_user_id(
                advertiser_id
            )
            if advertiser_profile is None:
                raise OrderCreationError("Advertiser profile is not set.")
        else:
            async with self.transaction_manager.transaction() as session:
                user = await self.user_repo.get_by_id(advertiser_id, session=session)
                if user is None:
                    raise UserNotFoundError("Advertiser not found.")

                advertiser_profile = await self.advertiser_repo.get_by_user_id(
                    advertiser_id, session=session
                )
                if advertiser_profile is None:
                    raise OrderCreationError("Advertiser profile is not set.")

        if user.status == UserStatus.BLOCKED:
            raise OrderCreationError("Blocked users cannot create orders.")
        if user.status == UserStatus.PAUSE:
            raise OrderCreationError("Paused users cannot create orders.")

        product_link = product_link.strip()
        if not product_link:
            raise OrderCreationError("Product link is required.")

        offer_text = offer_text.strip()
        if not offer_text:
            raise OrderCreationError("Offer text is required.")

        barter_description = (barter_description or "").strip() or None
        if price < 0:
            raise OrderCreationError("Price cannot be negative.")
        if price <= 0 and not barter_description:
            raise OrderCreationError("Price must be positive when no barter.")

        if bloggers_needed not in _ALLOWED_BLOGGER_COUNTS:
            raise OrderCreationError("Invalid bloggers count.")

        is_new = await self.is_new_advertiser(advertiser_id)
        if is_new and barter_description:
            raise OrderCreationError("Barter is not available for NEW advertisers.")
        if is_new and bloggers_needed > 10:
            raise OrderCreationError("NEW advertisers can request up to 10 bloggers.")

        order = Order(
            order_id=uuid4(),
            advertiser_id=advertiser_id,
            order_type=order_type,
            product_link=product_link,
            offer_text=offer_text,
            ugc_requirements=(ugc_requirements or "").strip() or None,
            barter_description=barter_description,
            price=price,
            bloggers_needed=bloggers_needed,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            contacts_sent_at=None,
        )
        if self.transaction_manager is None:
            await self.order_repo.save(order)
        else:
            async with self.transaction_manager.transaction() as session:
                await self.order_repo.save(order, session=session)

        logger.info(
            "Order created",
            extra={
                "order_id": str(order.order_id),
                "advertiser_id": str(order.advertiser_id),
                "price": float(order.price),
                "bloggers_needed": order.bloggers_needed,
                "event_type": "order.created",
            },
        )

        if self.metrics_collector:
            self.metrics_collector.record_order_created(
                order_id=str(order.order_id),
                advertiser_id=str(order.advertiser_id),
                price=float(order.price),
                bloggers_needed=order.bloggers_needed,
            )

        return order
