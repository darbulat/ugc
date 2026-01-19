"""Service for dispatching offers to bloggers."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    OrderRepository,
    UserRepository,
)
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import OrderStatus, UserStatus


@dataclass(slots=True)
class OfferDispatchService:
    """Select eligible bloggers for offers."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    order_repo: OrderRepository

    def dispatch(self, order_id: UUID) -> list[User]:
        """Return eligible bloggers for an active order."""

        order = self.order_repo.get_by_id(order_id)
        if order is None:
            raise OrderCreationError("Order not found.")
        if order.status != OrderStatus.ACTIVE:
            raise OrderCreationError("Order is not active.")

        confirmed_ids = self.blogger_repo.list_confirmed_user_ids()
        if not confirmed_ids:
            return []

        users: list[User] = []
        for user_id in confirmed_ids:
            user = self.user_repo.get_by_id(user_id)
            if user is None:
                continue
            if user.status != UserStatus.ACTIVE:
                continue
            users.append(user)
        return users

    def format_offer(self, order: Order, advertiser_status: str) -> str:
        """Format offer text for a blogger."""

        return (
            "Новый оффер:\n"
            f"Ссылка на продукт: {order.product_link}\n"
            f"Описание: {order.offer_text}\n"
            f"Цена за 1 UGC: {order.price}\n"
            f"Нужно блогеров: {order.bloggers_needed}\n"
            f"Рекламодатель: {advertiser_status}"
        )
