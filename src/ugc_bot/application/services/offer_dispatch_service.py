"""Service for dispatching offers to bloggers."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    OrderRepository,
    TransactionManager,
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
    transaction_manager: TransactionManager | None = None

    async def get_order_and_advertiser(
        self, order_id: UUID
    ) -> tuple[Order | None, User | None]:
        """Fetch order and its advertiser in one transaction."""

        if self.transaction_manager is None:
            order = await self.order_repo.get_by_id(order_id, session=None)
            if order is None:
                return (None, None)
            advertiser = await self.user_repo.get_by_id(
                order.advertiser_id, session=None
            )
            return (order, advertiser)

        async with self.transaction_manager.transaction() as session:
            order = await self.order_repo.get_by_id(order_id, session=session)
            if order is None:
                return (None, None)
            advertiser = await self.user_repo.get_by_id(
                order.advertiser_id, session=session
            )
            return (order, advertiser)

    async def dispatch(self, order_id: UUID) -> list[User]:
        """Return eligible bloggers for an active order."""

        if self.transaction_manager is None:
            return await self._dispatch(order_id, session=None)

        async with self.transaction_manager.transaction() as session:
            return await self._dispatch(order_id, session=session)

    async def _dispatch(self, order_id: UUID, session: object | None) -> list[User]:
        order = await self.order_repo.get_by_id(order_id, session=session)
        if order is None:
            raise OrderCreationError("Order not found.")
        if order.status != OrderStatus.ACTIVE:
            raise OrderCreationError("Order is not active.")

        confirmed_ids = await self.blogger_repo.list_confirmed_user_ids(session=session)
        if not confirmed_ids:
            return []

        users: list[User] = []
        for user_id in confirmed_ids:
            if user_id == order.advertiser_id:
                continue
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                continue
            if user.status != UserStatus.ACTIVE:
                continue
            users.append(user)
        return users

    def format_offer(self, order: Order, advertiser_status: str) -> str:
        """Format offer text for a blogger (without product_link per TZ)."""

        format_label = (
            "UGC + размещение"
            if order.order_type.value == "ugc_plus_placement"
            else "UGC-видео для бренда"
        )
        parts = [
            "Новый заказ UGC",
            "",
            "📋 Детали заказа:",
            f"Формат: {format_label}",
            f"Задача: {order.offer_text}",
        ]
        if order.price > 0:
            parts.append(f"Бюджет: {order.price} ₽ за 1 UGC-видео")
        if order.barter_description:
            parts.append(f"Бартер: {order.barter_description}")
        parts.append(f"Нужно креаторов: {order.bloggers_needed}")
        parts.append("")
        parts.append(
            "⚠️ Важно: прочитайте оффер перед откликом. "
            "Риск блокировки при необоснованном отказе."
        )
        parts.append("")
        parts.append(
            "📋 Как это работает: отклик = готовность на условиях; "
            "после отклика заказчик получит ваш профиль, вы — детали и ссылку на продукт."
        )
        parts.append("")
        parts.append(
            "🔒 Безопасность сделки: превью с водяным знаком, "
            "оплата до финального контента, платформа не участвует в сделке."
        )
        return "\n".join(parts)
