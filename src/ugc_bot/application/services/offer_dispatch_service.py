"""Service for dispatching offers to bloggers."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.geography import (
    blogger_matches_geography,
    parse_geography,
)
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    InstagramStatsRepository,
    InteractionRepository,
    OfferDispatchRepository,
    OrderRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import OrderStatus, UserStatus
from ugc_bot.infrastructure.db.session import with_optional_tx


def _age_from_birth_date(birth_date: date | None, today: date) -> int | None:
    """Return full years age from birth_date, or None if birth_date is None."""
    if birth_date is None:
        return None
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


@dataclass(slots=True)
class OfferDispatchService:
    """Select eligible bloggers for offers."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    order_repo: OrderRepository
    offer_dispatch_repo: OfferDispatchRepository
    interaction_repo: InteractionRepository
    instagram_stats_repo: InstagramStatsRepository | None = None
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
        from ugc_bot.domain.entities import BloggerProfile

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

        min_followers = (
            order.min_followers if order.min_followers is not None else 0
        )
        max_followers = (
            order.max_followers if order.max_followers is not None else 0
        )
        min_followers_enabled = order.min_followers is not None
        max_followers_enabled = order.max_followers is not None
        min_publications_enabled = order.min_publications is not None
        max_publications_enabled = order.max_publications is not None
        min_age_enabled = order.min_age is not None
        max_age_enabled = order.max_age is not None
        gender_enabled = order.required_blogger_gender is not None

        need_profile = (
            geography_spec is not None
            or min_followers_enabled
            or max_followers_enabled
            or min_publications_enabled
            or max_publications_enabled
            or min_age_enabled
            or max_age_enabled
            or gender_enabled
        )
        need_instagram_stats = (
            (min_followers_enabled or max_followers_enabled)
            or (min_publications_enabled or max_publications_enabled)
        ) and self.instagram_stats_repo is not None

        today = date.today()

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
            profile: BloggerProfile | None = None
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
            followers_count: int | None = None
            media_count: int | None = None
            if need_instagram_stats and self.instagram_stats_repo:
                stats = await self.instagram_stats_repo.get_by_user_id(
                    user_id, session=session
                )
                if stats is not None:
                    followers_count = stats.followers_count
                    media_count = stats.media_count
            if (
                followers_count is None or media_count is None
            ) and profile is not None:
                if followers_count is None:
                    followers_count = profile.instagram_followers_count
                if media_count is None:
                    media_count = profile.instagram_media_count
            if min_followers_enabled:
                if followers_count is None:
                    continue
                if followers_count < min_followers:
                    continue
            if max_followers_enabled:
                if followers_count is None:
                    continue
                if followers_count > max_followers:
                    continue
            if min_publications_enabled and order.min_publications is not None:
                if media_count is None:
                    continue
                if media_count < order.min_publications:
                    continue
            if max_publications_enabled and order.max_publications is not None:
                if media_count is None:
                    continue
                if media_count > order.max_publications:
                    continue
            if min_age_enabled or max_age_enabled:
                if profile is None:
                    continue
                age = _age_from_birth_date(profile.birth_date, today)
                if age is None:
                    continue
                if order.min_age is not None and age < order.min_age:
                    continue
                if order.max_age is not None and age > order.max_age:
                    continue
            if gender_enabled and order.required_blogger_gender is not None:
                if profile is None or profile.blogger_gender is None:
                    continue
                if profile.blogger_gender != order.required_blogger_gender:
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
