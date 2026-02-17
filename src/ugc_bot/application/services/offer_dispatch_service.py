"""Service for dispatching offers to bloggers."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.geography import (
    blogger_matches_geography,
    parse_geography,
)
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    InteractionRepository,
    OfferDispatchRepository,
    OrderRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.config import OrderConfig
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import OrderStatus, UserStatus
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class OfferDispatchService:
    """Select eligible bloggers for offers."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    order_repo: OrderRepository
    offer_dispatch_repo: OfferDispatchRepository
    interaction_repo: InteractionRepository
    order_config: OrderConfig
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

    async def _dispatch(  # noqa: PLR0912
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

        already_sent = (
            await self.offer_dispatch_repo.list_blogger_ids_sent_for_order(
                order_id, session=session
            )
        )
        already_sent_set = frozenset(already_sent)

        unfulfilled_ids = await self.interaction_repo.list_blogger_ids_with_unfulfilled_interaction(  # noqa: E501
            session=session
        )
        bloggers_with_unfulfilled = frozenset(unfulfilled_ids)

        geography_spec = None
        if order.geography:
            geography_spec = parse_geography(order.geography)

        need_profile = (
            geography_spec is not None
            or self.order_config.offer_dispatch_min_followers_enabled
        )
        min_followers = self.order_config.offer_dispatch_min_followers

        users: list[User] = []
        for user_id in confirmed_ids:
            if user_id == order.advertiser_id:
                continue
            if user_id in already_sent_set:
                continue
            if user_id in bloggers_with_unfulfilled:
                continue
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                continue
            if user.status != UserStatus.ACTIVE:
                continue
            profile = None
            if need_profile:
                profile = await self.blogger_repo.get_by_user_id(
                    user_id, session=session
                )
                if profile is None:
                    continue
            if (
                geography_spec is not None
                and profile is not None
                and not blogger_matches_geography(
                    profile.city,
                    geography_spec,
                )
            ):
                continue
            if self.order_config.offer_dispatch_min_followers_enabled:
                if profile is None or profile.instagram_followers_count is None:
                    continue
                if profile.instagram_followers_count < min_followers:
                    continue
            users.append(user)
        return users

    async def record_offer_sent(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
    ) -> None:
        """Record that an offer was sent to a blogger for an order."""

        async def _run(sess: object | None) -> None:
            await self.offer_dispatch_repo.record_sent(
                order_id, blogger_id, session=sess
            )

        await with_optional_tx(self.transaction_manager, _run)

    async def record_skip(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
    ) -> None:
        """Record blogger skip (accepted=False, in_offer=False)."""

        async def _run(sess: object | None) -> None:
            await self.offer_dispatch_repo.record_response(
                order_id,
                blogger_id,
                accepted=False,
                in_offer=False,
                session=sess,
            )

        await with_optional_tx(self.transaction_manager, _run)

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
            "со стороны заказчика"
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
