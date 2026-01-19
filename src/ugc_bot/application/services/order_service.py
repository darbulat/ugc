"""Service for order creation and validation."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.ports import OrderRepository, UserRepository
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus, UserRole, UserStatus


_ALLOWED_BLOGGER_COUNTS = {3, 10, 20, 30, 50}


@dataclass(slots=True)
class OrderService:
    """Create advertiser orders with validation."""

    user_repo: UserRepository
    order_repo: OrderRepository

    def is_new_advertiser(self, advertiser_id: UUID) -> bool:
        """Return True when advertiser has no previous orders."""

        return self.order_repo.count_by_advertiser(advertiser_id) == 0

    def list_by_advertiser(self, advertiser_id: UUID) -> list[Order]:
        """List orders for advertiser."""

        return list(self.order_repo.list_by_advertiser(advertiser_id))

    def create_order(
        self,
        advertiser_id: UUID,
        product_link: str,
        offer_text: str,
        ugc_requirements: Optional[str],
        barter_description: Optional[str],
        price: float,
        bloggers_needed: int,
    ) -> Order:
        """Create an order after validating input."""

        user = self.user_repo.get_by_id(advertiser_id)
        if user is None:
            raise UserNotFoundError("Advertiser not found.")

        if user.role not in {UserRole.ADVERTISER, UserRole.BOTH}:
            raise OrderCreationError("User is not an advertiser.")

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

        if price <= 0:
            raise OrderCreationError("Price must be positive.")

        if bloggers_needed not in _ALLOWED_BLOGGER_COUNTS:
            raise OrderCreationError("Invalid bloggers count.")

        barter_description = (barter_description or "").strip() or None
        is_new = self.is_new_advertiser(advertiser_id)
        if is_new and barter_description:
            raise OrderCreationError("Barter is not available for NEW advertisers.")
        if is_new and bloggers_needed > 10:
            raise OrderCreationError("NEW advertisers can request up to 10 bloggers.")

        order = Order(
            order_id=uuid4(),
            advertiser_id=advertiser_id,
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
        self.order_repo.save(order)
        return order
