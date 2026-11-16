"""Shared dashboard counts and directory filters for the creator base."""

from typing import Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from ugc_bot.admin.business_metrics import (
    _creator_order_activity,
    _legacy_creator_picks,
)
from ugc_bot.admin.dashboard_periods import PeriodKey, dashboard_period_window
from ugc_bot.admin.order_worklist import business_order_conditions
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel
from ugc_bot.infrastructure.db.messenger_attribution import (
    OFFER_CHANNELS,
    REGISTRATION_CHANNELS,
)
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    InteractionModel,
    OfferDispatchModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    BOT_AVAILABLE_EVENT,
    BOT_UNAVAILABLE_EVENT,
    latest_bot_availability,
)

CREATOR_ACTIVITY_PERIODS = {
    "today": "Сегодня",
    "yesterday": "Вчера",
    "7d": "7 дней",
    "30d": "30 дней",
    "90d": "90 дней",
    "all": "Всё время",
}
CreatorPeriod = PeriodKey | Literal["90d"]
CREATOR_BASE_CARDS = (
    (
        "Регистрация",
        (
            ("profiles", "Всего профилей"),
            ("registered", "Завершили регистрацию"),
            ("no_agreement", "Ожидают принятия условий"),
            ("no_instagram", "Ожидают подтверждения Instagram"),
        ),
    ),
    (
        "Зарегистрированные креаторы",
        (
            ("registered_telegram", "С Telegram"),
            ("registered_max", "С MAX"),
            ("registered_both", "С Telegram и MAX"),
            ("registered_max_only", "Только с MAX"),
        ),
    ),
    (
        "Доступность Telegram",
        (
            ("telegram_account", "Есть аккаунт Telegram"),
            ("telegram_available", "Доступен"),
            ("telegram_unavailable", "Бот недоступен"),
            ("telegram_unknown", "Нет данных о доступности"),
        ),
    ),
    (
        "Доступность MAX",
        (
            ("max_account", "Есть аккаунт MAX"),
            ("max_available", "Доступен"),
            ("max_unavailable", "Бот недоступен"),
            ("max_unknown", "Нет данных о доступности"),
        ),
    ),
)
CREATOR_ACTIVITY_LABELS = {
    "offered": "Получили предложение",
    "accepted": "Приняли предложение",
    "worked": "Работали",
    "responded": "Все отклики",
}
MAX_ACTIVITY_LABELS = {
    "offered_via_max": "Получили предложение в MAX",
    "max_only_offer": "Получили хотя бы один оффер только в MAX",
    "max_only_reached": "Получали предложения только в MAX за период",
    "responded_via_max": "Откликнулись в MAX",
    "registered_via_max": "Завершили регистрацию через MAX",
}
CREATOR_FUNNEL_LABELS = {
    "funnel_profiles": "Создали профиль креатора",
    "funnel_agreements": "Приняли условия",
    "funnel_registered": "Завершили регистрацию",
    "funnel_no_agreement": "Ожидают принятия условий",
    "funnel_no_instagram": "Ожидают подтверждения Instagram",
}
CREATOR_BASE_LABELS = {
    **{key: label for _, items in CREATOR_BASE_CARDS for key, label in items},
    **CREATOR_ACTIVITY_LABELS,
    **MAX_ACTIVITY_LABELS,
    **CREATOR_FUNNEL_LABELS,
    "telegram_available": "Telegram · доступен",
    "telegram_unavailable": "Telegram · бот недоступен",
    "telegram_unknown": "Telegram · нет данных о доступности",
    "max_available": "MAX · доступен",
    "max_unavailable": "MAX · бот недоступен",
    "max_unknown": "MAX · нет данных о доступности",
}


def normalize_creator_period(period: str) -> CreatorPeriod:
    return (
        cast(CreatorPeriod, period)
        if period in CREATOR_ACTIVITY_PERIODS
        else "30d"
    )


def _registration_stages() -> dict[str, ColumnElement[bool]]:
    profile = BloggerProfileModel
    saved = profile.user_id.is_not(None)
    agreement = profile.agreement_confirmed_at.is_not(None)
    verified = profile.confirmed.is_(True)
    return {
        "funnel_profiles": saved,
        "funnel_agreements": agreement,
        "funnel_registered": agreement & verified,
        "funnel_no_agreement": saved & ~agreement,
        "funnel_no_instagram": agreement & ~verified,
    }


def _profile_conditions() -> dict[str, ColumnElement[bool]]:
    user = UserModel
    profile = BloggerProfileModel
    agreement = profile.agreement_confirmed_at.is_not(None)
    registered = agreement & profile.confirmed.is_(True)
    telegram = func.nullif(func.trim(user.telegram_id), "").is_not(None)
    max_id = func.nullif(func.trim(user.max_id), "").is_not(None)
    return {
        "profiles": user.user_id.is_not(None),
        "registered": registered,
        "no_agreement": ~agreement,
        "no_instagram": agreement & profile.confirmed.is_not(True),
        "registered_telegram": registered & telegram,
        "registered_max": registered & max_id,
        "registered_both": registered & telegram & max_id,
        "registered_max_only": registered & max_id & ~telegram,
        "telegram_account": telegram,
        "max_account": max_id,
        **_availability(MessengerType.TELEGRAM, telegram),
        **_availability(MessengerType.MAX, max_id),
    }


def _availability(platform, linked) -> dict[str, ColumnElement[bool]]:
    latest = latest_bot_availability(platform)
    has_no_event = latest.is_(None)
    unavailable = latest == BOT_UNAVAILABLE_EVENT
    unknown = has_no_event
    if platform == MessengerType.TELEGRAM:
        # Older delivery failures have no channel recorded. Only infer Telegram
        # when the profile's primary and sole route identifies that channel.
        legacy = and_(
            UserModel.status == UserStatus.BOT_BLOCKED,
            UserModel.messenger_type == MessengerType.TELEGRAM,
            func.nullif(func.trim(UserModel.max_id), "").is_(None),
            func.nullif(func.trim(UserModel.max_chat_id), "").is_(None),
        )
        unavailable = or_(unavailable, has_no_event & legacy)
        unknown = has_no_event & ~legacy
    return {
        f"{platform}_available": linked & (latest == BOT_AVAILABLE_EVENT),
        f"{platform}_unavailable": linked & unavailable,
        f"{platform}_unknown": linked & unknown,
    }


def _current_work():
    dispatch = OfferDispatchModel
    work = CollaborationModel
    interactions = (
        select(InteractionModel.interaction_id)
        .where(
            InteractionModel.order_id == dispatch.order_id,
            InteractionModel.blogger_id == dispatch.blogger_id,
            InteractionModel.advertiser_id == OrderModel.advertiser_id,
        )
        .correlate(dispatch, OrderModel)
    )
    open_interaction = interactions.where(
        InteractionModel.status.in_(
            (InteractionStatus.PENDING, InteractionStatus.ISSUE)
        )
    ).exists()
    legacy = _legacy_creator_picks().where(
        dispatch.accepted.is_(True),
        or_(
            open_interaction,
            (OrderModel.status == OrderStatus.ACTIVE) & ~interactions.exists(),
        ),
    )
    paid = (
        select(work.creator_id.label("creator"))
        .join(OrderModel, OrderModel.order_id == work.order_id)
        .where(work.state == "in_progress", *business_order_conditions())
    )
    return legacy.union(paid)


def _activity_conditions(
    period: CreatorPeriod, timezone: ZoneInfo
) -> dict[str, ColumnElement[bool]]:
    window = dashboard_period_window(period, timezone)

    def in_window(column):
        return and_(column >= window.current_start, column < window.current_end)

    dispatch = OfferDispatchModel
    offers = (
        select(dispatch.blogger_id)
        .join(OrderModel, OrderModel.order_id == dispatch.order_id)
        .where(*business_order_conditions())
    )
    response_at = func.coalesce(dispatch.updated_at, dispatch.created_at)
    responses = offers.where(
        dispatch.accepted.is_not(None), in_window(response_at)
    )
    activity = _creator_order_activity()
    started = select(activity.c.creator).where(in_window(activity.c.at))
    work = (
        started
        if period == "yesterday"
        else started.union(select(_current_work().subquery().c.creator))
    )
    channels = OFFER_CHANNELS.c
    tracked = (
        select(channels.blogger_id)
        .join(OrderModel, OrderModel.order_id == channels.order_id)
        .where(*business_order_conditions())
    )
    max_offers = tracked.where(in_window(channels.max_sent_at))
    telegram_offers = tracked.where(in_window(channels.telegram_sent_at))
    registration = REGISTRATION_CHANNELS.c
    user_id = UserModel.user_id
    return {
        "offered_via_max": user_id.in_(max_offers),
        "max_only_offer": user_id.in_(
            max_offers.where(channels.telegram_sent_at.is_(None))
        ),
        "max_only_reached": user_id.in_(max_offers)
        & user_id.not_in(telegram_offers),
        "responded_via_max": user_id.in_(
            tracked.where(
                channels.response_channel == MessengerType.MAX,
                in_window(channels.response_at),
            )
        ),
        "registered_via_max": user_id.in_(
            select(registration.user_id).where(
                registration.channel == MessengerType.MAX,
                in_window(registration.completed_at),
            )
        ),
        "offered": UserModel.user_id.in_(
            offers.where(in_window(dispatch.created_at))
        ),
        "responded": UserModel.user_id.in_(responses),
        "accepted": UserModel.user_id.in_(
            responses.where(dispatch.accepted.is_(True))
        ),
        "worked": user_id.in_(work),
    }


def creator_base_filter(
    segment: str, period: str, timezone: ZoneInfo
) -> ColumnElement[bool]:
    normalized = normalize_creator_period(period)
    if segment in CREATOR_FUNNEL_LABELS:
        return and_(
            UserModel.status != UserStatus.DELETED,
            _new_accounts(normalized, timezone),
            _registration_stages()[segment],
        )
    conditions = (
        _activity_conditions(normalized, timezone)
        if segment in CREATOR_ACTIVITY_LABELS or segment in MAX_ACTIVITY_LABELS
        else _profile_conditions()
    )
    return and_(UserModel.status != UserStatus.DELETED, conditions[segment])


def _new_accounts(
    period: CreatorPeriod, timezone: ZoneInfo
) -> ColumnElement[bool]:
    window = dashboard_period_window(period, timezone)
    return and_(
        UserModel.created_at >= window.current_start,
        UserModel.created_at < window.current_end,
    )


async def creator_base_counts(
    db: AsyncSession, period: str, timezone: ZoneInfo
) -> dict[str, int]:
    normalized = normalize_creator_period(period)
    conditions = {
        **_profile_conditions(),
        **_activity_conditions(normalized, timezone),
    }
    result = await db.execute(
        select(
            *(
                func.count().filter(condition).label(name)
                for name, condition in conditions.items()
            )
        )
        .select_from(BloggerProfileModel)
        .join(UserModel, UserModel.user_id == BloggerProfileModel.user_id)
        .where(UserModel.status != UserStatus.DELETED)
    )
    funnel = await db.execute(
        select(
            func.count().label("funnel_accounts"),
            *(
                func.count().filter(condition).label(name)
                for name, condition in _registration_stages().items()
            ),
        )
        .select_from(UserModel)
        .outerjoin(
            BloggerProfileModel,
            BloggerProfileModel.user_id == UserModel.user_id,
        )
        .where(
            UserModel.status != UserStatus.DELETED,
            _new_accounts(normalized, timezone),
        )
    )
    return {**result.one()._mapping, **funnel.one()._mapping}
