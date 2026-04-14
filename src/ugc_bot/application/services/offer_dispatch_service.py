"""Service for dispatching offers to bloggers."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ugc_bot.application.errors import (
    OrderNotActiveError,
    OrderNotFoundError,
)
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    BloggerRatingRepository,
    CountryRepository,
    InstagramStatsRepository,
    InteractionRepository,
    ManagerOrderRepository,
    OfferDispatchRepository,
    OrderRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.domain.entities import BloggerProfile, InstagramStats, Order, User
from ugc_bot.domain.enums import (
    OrderStatus,
    OrderType,
    RejectionReason,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(frozen=True)
class _DispatchCriteria:
    """Parsed filter criteria for offer dispatch."""

    min_followers: int
    max_followers: int
    min_followers_enabled: bool
    max_followers_enabled: bool
    min_publications_enabled: bool
    max_publications_enabled: bool
    min_age_enabled: bool
    max_age_enabled: bool
    gender_enabled: bool
    filter_by_price: bool
    price_filter_delta: float | None
    min_rating: float | None
    min_rating_enabled: bool
    filter_by_placement: bool
    filter_by_barter: bool
    need_profile: bool
    need_instagram_stats: bool
    today: date


def _age_from_birth_date(birth_date: date | None, today: date) -> int | None:
    """Return full years age from birth_date, or None if birth_date is None."""
    if birth_date is None:
        return None
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def _build_dispatch_criteria(
    order: Order, *, has_instagram_stats_repo: bool = False
) -> _DispatchCriteria:
    """Build parsed filter criteria from order for dispatch loop."""
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
    filter_by_price = getattr(order, "filter_by_price", False)
    price_filter_delta_raw = getattr(order, "price_filter_delta", None)
    price_filter_delta = (
        float(price_filter_delta_raw)
        if price_filter_delta_raw is not None
        else None
    )
    filter_by_placement = getattr(order, "filter_by_placement", False)
    filter_by_barter = getattr(order, "filter_by_barter", False)
    min_rating_raw = getattr(order, "min_rating", None)
    min_rating = float(min_rating_raw) if min_rating_raw is not None else None
    min_rating_enabled = min_rating is not None
    need_profile = (
        min_followers_enabled
        or max_followers_enabled
        or min_publications_enabled
        or max_publications_enabled
        or min_age_enabled
        or max_age_enabled
        or gender_enabled
        or filter_by_price
        or filter_by_placement
        or filter_by_barter
    )
    need_instagram_stats = (
        (min_followers_enabled or max_followers_enabled)
        or (min_publications_enabled or max_publications_enabled)
    ) and has_instagram_stats_repo
    return _DispatchCriteria(
        min_followers=min_followers,
        max_followers=max_followers,
        min_followers_enabled=min_followers_enabled,
        max_followers_enabled=max_followers_enabled,
        min_publications_enabled=min_publications_enabled,
        max_publications_enabled=max_publications_enabled,
        min_age_enabled=min_age_enabled,
        max_age_enabled=max_age_enabled,
        gender_enabled=gender_enabled,
        filter_by_price=filter_by_price,
        price_filter_delta=price_filter_delta,
        min_rating=min_rating,
        min_rating_enabled=min_rating_enabled,
        filter_by_placement=filter_by_placement,
        filter_by_barter=filter_by_barter,
        need_profile=need_profile,
        need_instagram_stats=need_instagram_stats,
        today=date.today(),
    )


def _passes_follower_filters(
    followers_count: int | None, criteria: _DispatchCriteria
) -> bool:
    """Return True if followers_count passes min/max follower filters."""
    if criteria.min_followers_enabled and (
        followers_count is None or followers_count < criteria.min_followers
    ):
        return False
    fails_max = criteria.max_followers_enabled and (
        followers_count is None or followers_count > criteria.max_followers
    )
    return not fails_max


def _passes_publication_filters(
    media_count: int | None, order: Order, criteria: _DispatchCriteria
) -> bool:
    """Return True if media_count passes min/max publication filters."""
    fails_min = (
        criteria.min_publications_enabled
        and order.min_publications is not None
        and (media_count is None or media_count < order.min_publications)
    )
    if fails_min:
        return False
    fails_max = (
        criteria.max_publications_enabled
        and order.max_publications is not None
        and (media_count is None or media_count > order.max_publications)
    )
    return not fails_max


def _passes_age_filters(
    profile: BloggerProfile | None, order: Order, criteria: _DispatchCriteria
) -> bool:
    """Return True if profile age passes min/max age filters."""
    if not criteria.min_age_enabled and not criteria.max_age_enabled:
        return True
    if profile is None:
        return False
    age = _age_from_birth_date(profile.birth_date, criteria.today)
    if age is None:
        return False
    if order.min_age is not None and age < order.min_age:
        return False
    return not (order.max_age is not None and age > order.max_age)


def _passes_gender_filter(profile: BloggerProfile | None, order: Order) -> bool:
    """Return True if profile gender matches order requirement."""
    if order.required_blogger_gender is None:
        return True
    if profile is None or profile.blogger_gender is None:
        return False
    return profile.blogger_gender == order.required_blogger_gender


def _passes_price_filter(
    profile: BloggerProfile | None, order: Order, criteria: _DispatchCriteria
) -> bool:
    """True if creator price in [order.price - delta, order.price + delta]."""
    if not criteria.filter_by_price or criteria.price_filter_delta is None:
        return True
    if profile is None:
        return False
    delta = criteria.price_filter_delta
    low = max(0.0, order.price - delta)
    high = order.price + delta
    price = float(profile.price)
    return low <= price <= high


def _passes_placement_filter(
    profile: BloggerProfile | None, order: Order, criteria: _DispatchCriteria
) -> bool:
    """True if creator work_format matches order type when filter enabled."""
    if not criteria.filter_by_placement:
        return True
    if profile is None:
        return False
    if order.order_type == OrderType.UGC_PLUS_PLACEMENT:
        return profile.work_format == WorkFormat.ADS_IN_ACCOUNT
    return True


def _passes_barter_filter(
    profile: BloggerProfile | None, order: Order, criteria: _DispatchCriteria
) -> bool:
    """True if creator accepts barter when filter enabled."""
    if not criteria.filter_by_barter:
        return True
    if profile is None:
        return False
    return profile.barter is True


def _passes_order_filters(
    profile: BloggerProfile | None, order: Order, criteria: _DispatchCriteria
) -> bool:
    """True if profile passes price, placement, and barter filters."""
    return (
        _passes_price_filter(profile, order, criteria)
        and _passes_placement_filter(profile, order, criteria)
        and _passes_barter_filter(profile, order, criteria)
    )


def _passes_profile_based_filters(
    profile: BloggerProfile | None, order: Order, criteria: _DispatchCriteria
) -> bool:
    """True if profile passes age, gender, and order filters."""
    if not _passes_age_filters(profile, order, criteria):
        return False
    if not _passes_gender_filter(profile, order):
        return False
    return _passes_order_filters(profile, order, criteria)


def _extract_followers_and_media(
    stats: InstagramStats | None,
    profile: BloggerProfile | None,
    criteria: _DispatchCriteria,
) -> tuple[int | None, int | None]:
    """Resolve followers/media counts from pre-loaded stats and profile."""
    followers_count: int | None = None
    media_count: int | None = None
    if criteria.need_instagram_stats and stats is not None:
        followers_count = stats.followers_count
        media_count = stats.media_count
    if profile is not None and followers_count is None:
        followers_count = profile.instagram_followers_count
    return followers_count, media_count


@dataclass(slots=True)
class SkipResult:
    """Result of recording a skip with rejection reason."""

    rejection_reason: RejectionReason | None = None
    desired_price: Decimal | None = None
    manager_id: UUID | None = None
    order_price: Decimal | None = None
    offer_text: str | None = None
    product_link: str | None = None


@dataclass(slots=True)
class OfferDispatchService:
    """Select eligible bloggers for offers."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    order_repo: OrderRepository
    offer_dispatch_repo: OfferDispatchRepository
    interaction_repo: InteractionRepository
    instagram_stats_repo: InstagramStatsRepository | None = None
    blogger_rating_repo: BloggerRatingRepository | None = None
    country_repo: CountryRepository | None = None
    manager_order_repo: ManagerOrderRepository | None = None
    transaction_manager: TransactionManager | None = None
    currency_symbol: str = "₽"

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

    async def count_eligible_bloggers(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Return number of creators matching the order (any status)."""

        async def _run(sess: object | None) -> int:
            order = await self.order_repo.get_by_id(order_id, session=sess)
            (
                _order,
                confirmed_ids,
                already_sent_set,
                bloggers_with_unfulfilled,
            ) = await self._get_initial_data_for_order(
                order_id, order, session=sess
            )
            if _order is None or not confirmed_ids:
                return 0
            users = await self._collect_eligible_users(
                _order,
                confirmed_ids,
                already_sent_set,
                bloggers_with_unfulfilled,
                sess,
            )
            return len(users)

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)

    async def _validate_and_get_initial_data(
        self, order_id: UUID, session: object | None
    ) -> tuple[
        Order,
        list[UUID],
        frozenset[UUID],
        frozenset[UUID],
    ]:
        """Load order, validate active, return ids and exclusion sets."""
        order = await self.order_repo.get_by_id(order_id, session=session)
        if order is None:
            raise OrderNotFoundError("Order not found.")
        if order.status != OrderStatus.ACTIVE:
            raise OrderNotActiveError("Order is not active.")
        ord, cids, aset, uful = await self._get_initial_data_for_order(
            order_id, order, session
        )
        assert ord is not None
        return (ord, cids, aset, uful)

    async def _get_initial_data_for_order(
        self,
        order_id: UUID,
        order: Order | None,
        session: object | None,
    ) -> tuple[
        Order | None,
        list[UUID],
        frozenset[UUID],
        frozenset[UUID],
    ]:
        """Load confirmed ids and exclusion sets (no status check)."""
        if order is None:
            return None, [], frozenset(), frozenset()
        confirmed_ids = await self.blogger_repo.list_confirmed_user_ids(
            session=session,
            location_geometry_wkt=order.location_geometry,
        )
        if not confirmed_ids:
            return order, [], frozenset(), frozenset()
        already_sent = (
            await self.offer_dispatch_repo.list_blogger_ids_sent_for_order(
                order_id, session=session
            )
        )
        unfulfilled_ids = await self.interaction_repo.list_blogger_ids_with_unfulfilled_interaction(  # noqa: E501
            session=session
        )
        return (
            order,
            confirmed_ids,
            frozenset(already_sent),
            frozenset(unfulfilled_ids),
        )

    async def _collect_eligible_users(
        self,
        order: Order,
        confirmed_ids: list[UUID],
        already_sent_set: frozenset[UUID],
        bloggers_with_unfulfilled: frozenset[UUID],
        session: object | None,
    ) -> list[User]:
        """Batch-load and filter eligible users for an order.

        Replaces the N+1 loop in _dispatch/count_eligible_bloggers with
        3 batched queries: users, profiles, instagram stats.
        """
        criteria = _build_dispatch_criteria(
            order,
            has_instagram_stats_repo=self.instagram_stats_repo is not None,
        )

        # Pre-filter in memory — no DB calls
        candidate_ids = [
            uid
            for uid in confirmed_ids
            if uid != order.advertiser_id
            and uid not in already_sent_set
            and uid not in bloggers_with_unfulfilled
        ]
        if not candidate_ids:
            return []

        # Batch load users (1 query)
        users_map = await self.user_repo.get_by_ids(
            candidate_ids, session=session
        )
        active_ids = [
            uid
            for uid in candidate_ids
            if uid in users_map and users_map[uid].status == UserStatus.ACTIVE
        ]
        if not active_ids:
            return []

        # Batch load profiles if any profile-based filter is active (1 query)
        profiles_map: dict[UUID, BloggerProfile] = {}
        if criteria.need_profile:
            profiles_map = await self.blogger_repo.get_by_user_ids(
                active_ids, session=session
            )
            active_ids = [
                uid
                for uid in active_ids
                if uid in profiles_map
                and _passes_profile_based_filters(
                    profiles_map[uid], order, criteria
                )
            ]
        if not active_ids:
            return []

        # Batch load Instagram stats if needed (1 query)
        stats_map: dict[UUID, InstagramStats] = {}
        if (
            criteria.need_instagram_stats
            and self.instagram_stats_repo is not None
        ):
            stats_map = await self.instagram_stats_repo.get_by_user_ids(
                active_ids, session=session
            )

        # Final follower/publication filter in memory
        seen_ids: set[UUID] = set()
        users: list[User] = []
        for uid in active_ids:
            profile = profiles_map.get(uid)
            stats = stats_map.get(uid)
            followers_count, media_count = _extract_followers_and_media(
                stats, profile, criteria
            )
            if not _passes_follower_filters(followers_count, criteria):
                continue
            if not _passes_publication_filters(media_count, order, criteria):
                continue
            if uid not in seen_ids:
                seen_ids.add(uid)
                users.append(users_map[uid])

        return await self._apply_rating_rules(users, criteria, session)

    async def _apply_rating_rules(
        self,
        users: list[User],
        criteria: _DispatchCriteria,
        session: object | None,
    ) -> list[User]:
        """Apply rating filter and sort when rating repository is configured."""
        if self.blogger_rating_repo is None:
            return users
        ratings_map = (
            await self.blogger_rating_repo.get_avg_ratings_for_bloggers(
                [user.user_id for user in users],
                session=session,
            )
        )
        return self._apply_rating_filter_and_sort(users, ratings_map, criteria)

    def _apply_rating_filter_and_sort(
        self,
        users: list[User],
        ratings_map: dict[UUID, float],
        criteria: _DispatchCriteria,
    ) -> list[User]:
        """Filter by min rating and sort by avg rating descending."""
        if not users:
            return []

        eligible_users: list[User] = []
        for user in users:
            avg_rating = ratings_map.get(user.user_id)
            if (
                criteria.min_rating_enabled
                and avg_rating is not None
                and criteria.min_rating is not None
                and avg_rating < criteria.min_rating
            ):
                continue
            eligible_users.append(user)

        return sorted(
            eligible_users,
            key=lambda user: (
                ratings_map.get(user.user_id) is None,
                -(ratings_map.get(user.user_id) or 0.0),
            ),
        )

    async def _dispatch(
        self, order_id: UUID, session: object | None
    ) -> list[User]:
        """Return list of eligible bloggers for the order."""
        (
            order,
            confirmed_ids,
            already_sent_set,
            bloggers_with_unfulfilled,
        ) = await self._validate_and_get_initial_data(order_id, session)
        if not confirmed_ids:
            return []
        return await self._collect_eligible_users(
            order,
            confirmed_ids,
            already_sent_set,
            bloggers_with_unfulfilled,
            session,
        )

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

    async def get_order_price_bounds(
        self,
        order_id: UUID,
    ) -> tuple[Decimal, Decimal] | None:
        """Return (min_price, max_price) for desired price validation.

        Returns None if order not found.
        """
        order = await self.order_repo.get_by_id(order_id)
        if order is None:
            return None
        offer_price = Decimal(str(order.price))
        return offer_price, offer_price * 10

    async def record_skip(
        self,
        order_id: UUID,
        blogger_id: UUID,
        rejection_reason: RejectionReason | None = None,
        desired_price: Decimal | None = None,
        session: object | None = None,
    ) -> SkipResult:
        """Record blogger skip with optional rejection reason."""

        async def _run(sess: object | None) -> SkipResult:
            await self.offer_dispatch_repo.record_response(
                order_id,
                blogger_id,
                accepted=False,
                in_offer=False,
                session=sess,
                rejection_reason=rejection_reason.value
                if rejection_reason
                else None,
                desired_price=desired_price,
            )
            manager_id: UUID | None = None
            order_price: Decimal | None = None
            offer_text: str | None = None
            product_link: str | None = None
            if (
                rejection_reason == RejectionReason.LOW_PRICE
                and self.manager_order_repo
            ):
                assignments = await self.manager_order_repo.list_by_order(
                    order_id, session=sess
                )
                if assignments:
                    manager_id = assignments[0].user_id
                order = await self.order_repo.get_by_id(order_id, session=sess)
                if order:
                    order_price = Decimal(str(order.price))
                    offer_text = order.offer_text
                    product_link = order.product_link or None
            return SkipResult(
                rejection_reason=rejection_reason,
                desired_price=desired_price,
                manager_id=manager_id,
                order_price=order_price,
                offer_text=offer_text,
                product_link=product_link,
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def format_offer(
        self,
        order: Order,
        advertiser_status: str,
        locale: str = "ru",
        bot_texts_service: BotTextsService | None = None,
        session: object | None = None,
    ) -> str:
        """Format offer text for a blogger using localized texts."""
        currency_symbol = self.currency_symbol
        if self.country_repo is not None:
            country = await self.country_repo.get_by_currency_code(
                order.currency, session=session
            )
            if country is not None:
                currency_symbol = country.currency_symbol

        # Fetch localized texts
        texts: dict[str, str] = {}
        if bot_texts_service is not None:
            keys = [
                "offer_header",
                "offer_details_header",
                "offer_format",
                "offer_task",
                "offer_budget",
                "offer_barter",
                "offer_content_usage",
                "offer_deadlines",
                "offer_geography",
                "offer_bloggers_needed",
                "offer_warning",
                "offer_how_it_works",
                "offer_format_label_ugc_placement",
                "offer_format_label_ugc_only",
            ]
            texts = await bot_texts_service.get_many(keys, locale)

        def t(key: str, default: str) -> str:
            return texts.get(key) or default

        format_label = (
            t("offer_format_label_ugc_placement", "UGC + размещение")
            if order.order_type.value == "ugc_plus_placement"
            else t("offer_format_label_ugc_only", "UGC-видео для бренда")
        )

        parts = [
            t("offer_header", "Новый заказ"),
            "",
            t("offer_details_header", "📋 Детали заказа:"),
            t("offer_format", "🎥 Формат: {format_label}").format(
                format_label=format_label
            ),
            t("offer_task", "📝 Задача: {task}").format(task=order.offer_text),
        ]
        if order.price > 0:
            parts.append(
                t(
                    "offer_budget",
                    "💰 Бюджет: {price} {currency} за 1 UGC-видео",
                ).format(price=order.price, currency=currency_symbol)
            )
        if order.barter_description:
            parts.append(
                t("offer_barter", "🎁 Бартер: {description}").format(
                    description=order.barter_description
                )
            )
        if order.content_usage:
            parts.append(
                t("offer_content_usage", "📢 Использование: {usage}").format(
                    usage=order.content_usage
                )
            )
        if order.deadlines:
            parts.append(
                t("offer_deadlines", "⏱ Сроки: {deadlines}").format(
                    deadlines=order.deadlines
                )
            )
        if order.geography:
            parts.append(
                t("offer_geography", "📍 География: {geography}").format(
                    geography=order.geography
                )
            )
        parts.append(
            t("offer_bloggers_needed", "👥 Нужно креаторов: {count}").format(
                count=order.bloggers_needed
            )
        )
        parts.append("")
        parts.append(
            t(
                "offer_warning",
                "⚠️ Важно\n"
                "🧷 Откликайтесь только если готовы работать "
                "на указанных условиях\n"
                "❗ Отказ после отклика без изменения условий "
                "со стороны заказчика"
                "   может привести к жалобе и ограничению аккаунта",
            )
        )
        parts.append("")
        parts.append(
            t(
                "offer_how_it_works",
                "⏳ Как это работает\n"
                "● Вы откликаетесь на оффер\n"
                "● Получаете ссылку на продукт\n"
                "● Заказчик получает ваш профиль и пишет вам первым\n"
                "● Платформа не участвует в переговорах и оплате",
            )
        )
        return "\n".join(parts)
