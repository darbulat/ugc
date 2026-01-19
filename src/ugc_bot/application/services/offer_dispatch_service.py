"""Service for dispatching offers to bloggers."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    BloggerRelevanceSelector,
    OrderRepository,
    UserRepository,
)
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import OrderStatus, UserRole, UserStatus


@dataclass(slots=True)
class OfferDispatchService:
    """Select eligible bloggers for offers."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    order_repo: OrderRepository
    relevance_selector: BloggerRelevanceSelector

    def dispatch(self, order_id: UUID) -> list[User]:
        """Return eligible bloggers for an active order."""

        order = self.order_repo.get_by_id(order_id)
        if order is None:
            raise OrderCreationError("Order not found.")
        if order.status != OrderStatus.ACTIVE:
            raise OrderCreationError("Order is not active.")

        profiles = self.blogger_repo.list_confirmed_profiles()
        if not profiles:
            return []

        max_candidates = max(1, min(len(profiles), order.bloggers_needed * 3))
        selected_ids = self.relevance_selector.select(
            order=order,
            profiles=profiles,
            limit=max_candidates,
        )
        if not selected_ids:
            selected_ids = [profile.user_id for profile in profiles][:max_candidates]

        users: list[User] = []
        for user_id in selected_ids:
            user = self.user_repo.get_by_id(user_id)
            if user is None:
                continue
            if user.role not in {UserRole.BLOGGER, UserRole.BOTH}:
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
