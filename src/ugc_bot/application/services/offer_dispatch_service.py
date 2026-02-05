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
from ugc_bot.infrastructure.db.session import with_optional_tx


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

        async def _run(session: object | None):
            order = await self.order_repo.get_by_id(order_id, session=session)
            if order is None:
                return (None, None)
            advertiser = await self.user_repo.get_by_id(
                order.advertiser_id, session=session
            )
            return (order, advertiser)

        return await with_optional_tx(self.transaction_manager, _run)

    async def dispatch(self, order_id: UUID) -> list[User]:
        """Return eligible bloggers for an active order."""

        async def _run(session: object | None):
            return await self._dispatch(order_id, session=session)

        return await with_optional_tx(self.transaction_manager, _run)

    async def _dispatch(
        self, order_id: UUID, session: object | None
    ) -> list[User]:
        order = await self.order_repo.get_by_id(order_id, session=session)
        if order is None:
            raise OrderCreationError("Order not found.")
        if order.status != OrderStatus.ACTIVE:
            raise OrderCreationError("Order is not active.")

        confirmed_ids = await self.blogger_repo.list_confirmed_user_ids(
            session=session
        )
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
            "Новый заказ",
            "",
            "📋 Детали заказа:",
            f"🎥 Формат: {format_label}",
            f"📝 Задача: {order.offer_text}",
        ]
        if order.price > 0:
            parts.append(f"💰 Бюджет: {order.price} ₽ за 1 UGC-видео")
        if order.barter_description:
            parts.append(f"🎁 Бартер: {order.barter_description}")
        if order.content_usage:
            parts.append(f"📢 Использование: {order.content_usage}")
        if order.deadlines:
            parts.append(f"⏱ Сроки: {order.deadlines}")
        if order.geography:
            parts.append(f"📍 География: {order.geography}")
        parts.append(f"👥 Нужно креаторов: {order.bloggers_needed}")
        parts.append("")
        parts.append(
            "⚠️ Важно\n"
            "🧷 Откликайтесь только если готовы работать "
            "на указанных условиях\n"
            "❗ Отказ после отклика без изменения условий "
            "со стороны заказчика\n"
            "   может привести к жалобе и ограничению аккаунта"
        )
        parts.append("")
        parts.append(
            "⏳ Как это работает\n"
            "● Вы откликаетесь на оффер\n"
            "● Получаете ссылку на продукт\n"
            "● Заказчик получает ваш профиль и пишет вам первым\n"
            "● Платформа не участвует в переговорах и оплате"
        )
        return "\n".join(parts)
