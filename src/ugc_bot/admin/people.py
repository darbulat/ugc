"""Query filters and profile history for the admin directories."""

import re
from contextlib import suppress
from typing import TypedDict
from uuid import UUID

from sqlalchemy import (
    SQLColumnExpression,
    case,
    func,
    literal,
    not_,
    or_,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement

from ugc_bot.admin.creator_base import admin_creator_directory_status
from ugc_bot.admin.order_worklist import worklist_conditions
from ugc_bot.domain.enums import UserStatus
from ugc_bot.domain.social import (
    SOCIAL_PLATFORM_LABELS,
    SocialPlatform,
    normalize_social_url,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    BloggerRatingModel,
    ComplaintModel,
    InteractionModel,
    NpsResponseModel,
    OfferDispatchModel,
    OrderModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.ratings import (
    SqlAlchemyBloggerRatingRepository,
)
from ugc_bot.infrastructure.db.social_models import SocialAccountModel

PROFILE_HISTORY_PAGE_SIZE = 10
CREATOR_PLATFORM_LABELS = {
    **SOCIAL_PLATFORM_LABELS,
    SocialPlatform.OTHER: "Другая площадка",
}


class CreatorSocialSummary(TypedDict):
    platform: SocialPlatform
    label: str
    with_link: int
    with_followers: int
    without_followers: int


def instagram_audience_count() -> ColumnElement[int | None]:
    """Only nonnegative counts are usable in legacy Instagram profiles."""
    count = BloggerProfileModel.instagram_followers_count
    return case((count >= 0, count))


async def creator_social_summary(
    session: AsyncSession,
) -> list[CreatorSocialSummary]:
    profile = BloggerProfileModel
    account = SocialAccountModel
    instagram = (
        select(
            literal(SocialPlatform.INSTAGRAM.value),
            func.count(),
            func.count(instagram_audience_count()),
        )
        .select_from(UserModel)
        .join(profile)
        .where(func.trim(profile.instagram_url) != "")
    )
    additional = (
        select(
            account.platform, func.count(), func.count(account.followers_count)
        )
        .select_from(UserModel)
        .join(profile)
        .join(account, account.user_id == UserModel.user_id)
        .where(
            account.platform != SocialPlatform.INSTAGRAM,
            func.trim(account.url) != "",
        )
        .group_by(account.platform)
    )
    result = await session.execute(union_all(instagram, additional))
    counts = {
        platform: (with_link, with_followers)
        for platform, with_link, with_followers in result.all()
    }
    summary: list[CreatorSocialSummary] = []
    for platform, label in CREATOR_PLATFORM_LABELS.items():
        with_link, with_followers = counts.get(platform, (0, 0))
        summary.append(
            {
                "platform": platform,
                "label": label,
                "with_link": with_link,
                "with_followers": with_followers,
                "without_followers": with_link - with_followers,
            }
        )
    return summary


def _person_search(q: str | None, *profile_fields) -> list[ColumnElement[bool]]:
    term = (q or "").strip()
    if not term:
        return []
    handle = term.lstrip("@")
    escaped = (
        (handle or term)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    pattern = f"%{escaped}%"
    conditions: list[ColumnElement[bool]] = [
        field.ilike(pattern, escape="\\")
        for field in (UserModel.username, UserModel.telegram, *profile_fields)
    ]
    with suppress(ValueError):
        conditions.append(UserModel.user_id == UUID(term))  # type: ignore[arg-type]
    if term.isdigit():
        conditions.extend(
            (UserModel.telegram_id == term, UserModel.max_id == term)
        )
    return [or_(*conditions)]


def _complaint_filter(enabled: bool) -> list[ColumnElement[bool]]:
    if not enabled:
        return []
    return [
        select(ComplaintModel.complaint_id)
        .where(ComplaintModel.reported_id == UserModel.user_id)
        .exists()
    ]


def _audience_conditions(
    count: SQLColumnExpression[int | None],
    minimum: int | None,
    unknown: bool,
) -> list[ColumnElement[bool]]:
    if unknown:
        return [count.is_(None)]
    if minimum is not None and minimum >= 0:
        return [count >= minimum]
    return []


def creator_directory_filters(
    q: str | None,
    city: str,
    status: str,
    followers_min: int | None,
    with_complaints: bool,
    platform: SocialPlatform | None = None,
    *,
    platform_followers_min: int | None = None,
    platform_followers_unknown: bool = False,
) -> list[ColumnElement[bool]]:
    filters = _person_search(q, BloggerProfileModel.instagram_url)
    filters.extend(_complaint_filter(with_complaints))
    if city.strip():
        filters.append(
            func.lower(func.trim(BloggerProfileModel.city))
            == city.strip().lower()
        )
    if status == "active":
        filters.append(admin_creator_directory_status() == UserStatus.ACTIVE)
    elif status == "bot_blocked":
        filters.append(
            admin_creator_directory_status() == UserStatus.BOT_BLOCKED
        )
    elif status == "limited":
        filters.append(
            admin_creator_directory_status().not_in(
                (UserStatus.ACTIVE, UserStatus.BOT_BLOCKED)
            )
        )
    if followers_min is not None and followers_min >= 0:
        filters.append(
            BloggerProfileModel.instagram_followers_count >= followers_min
        )
    if platform == SocialPlatform.INSTAGRAM:
        filters.append(func.trim(BloggerProfileModel.instagram_url) != "")
        filters.extend(
            _audience_conditions(
                instagram_audience_count(),
                platform_followers_min,
                platform_followers_unknown,
            )
        )
    elif platform is not None:
        filters.append(
            select(SocialAccountModel.account_id)
            .where(
                SocialAccountModel.user_id == UserModel.user_id,
                SocialAccountModel.platform == platform,
                func.trim(SocialAccountModel.url) != "",
                *_audience_conditions(
                    SocialAccountModel.followers_count,
                    platform_followers_min,
                    platform_followers_unknown,
                ),
            )
            .correlate(UserModel)
            .exists()
        )
    return filters


async def creator_inviters(
    session: AsyncSession, creator_ids: list[UUID]
) -> dict[UUID, dict[str, str | None]]:
    """Read the registration referrer, independent of order assignments."""
    binding = UserReferralBindingModel
    rows = await session.execute(
        select(
            binding.referred_user_id,
            UserModel.user_id,
            UserModel.username,
            UserModel.telegram,
        )
        .join(UserModel, UserModel.user_id == binding.referrer_user_id)
        .where(binding.referred_user_id.in_(creator_ids))
    )
    return {
        creator_id: {
            "user_id": str(inviter_id),
            "username": username,
            "telegram": telegram,
        }
        for creator_id, inviter_id, username, telegram in rows.all()
    }


def advertiser_directory_filters(
    q: str | None, activity: str, with_complaints: bool
) -> list[ColumnElement[bool]]:
    filters = _person_search(
        q, AdvertiserProfileModel.brand, AdvertiserProfileModel.site_link
    )
    filters.extend(_complaint_filter(with_complaints))
    if activity in {"with_orders", "without_orders"}:
        has_orders = (
            select(OrderModel.order_id)
            .where(
                OrderModel.advertiser_id == UserModel.user_id,
                *worklist_conditions("all", ""),
            )
            .exists()
        )
        filters.append(
            has_orders if activity == "with_orders" else not_(has_orders)
        )
    return filters


def instagram_link(value: str | None) -> tuple[str, str] | None:
    if value:
        with suppress(ValueError):
            return normalize_social_url(SocialPlatform.INSTAGRAM, value)
    return None


def telegram_handle(value: str | None) -> str | None:
    handle = (value or "").strip().lstrip("@")
    return handle if re.fullmatch(r"[A-Za-z0-9_]{1,32}", handle) else None


def _interaction_feedback(user_id: UUID):
    """Read both directions, retaining the author and the order."""
    interaction = InteractionModel
    from_creator = select(
        interaction.interaction_id.label("entry_id"),
        interaction.blogger_id.label("author_id"),
        interaction.advertiser_id.label("target_id"),
        interaction.order_id.label("order_id"),
        interaction.from_blogger.label("message"),
        interaction.updated_at.label("date"),
    ).where(
        or_(
            interaction.advertiser_id == user_id,
            interaction.blogger_id == user_id,
        ),
        func.length(func.trim(interaction.from_blogger)) > 0,
    )
    from_customer = select(
        interaction.interaction_id,
        interaction.advertiser_id,
        interaction.blogger_id,
        interaction.order_id,
        interaction.from_advertiser,
        interaction.updated_at,
    ).where(
        or_(
            interaction.blogger_id == user_id,
            interaction.advertiser_id == user_id,
        ),
        func.length(func.trim(interaction.from_advertiser)) > 0,
    )
    feedback = union_all(from_creator, from_customer).subquery()
    author, target = aliased(UserModel), aliased(UserModel)
    return (
        select(
            feedback,
            author.username.label("author"),
            target.username.label("target"),
            OrderModel.offer_text,
        )
        .join(author, author.user_id == feedback.c.author_id)
        .join(target, target.user_id == feedback.c.target_id)
        .join(OrderModel, OrderModel.order_id == feedback.c.order_id)
        .order_by(
            feedback.c.date.desc(), feedback.c.entry_id, feedback.c.author_id
        )
    )


async def user_card_history(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_id: UUID,
    is_creator: bool,
    is_customer: bool,
    pages: dict[str, int],
) -> dict:
    history: dict = {}
    reporter, reported = aliased(UserModel), aliased(UserModel)
    complaints = (
        select(
            ComplaintModel,
            reporter.username.label("author"),
            reported.username.label("target"),
        )
        .join(reporter, reporter.user_id == ComplaintModel.reporter_id)
        .join(reported, reported.user_id == ComplaintModel.reported_id)
        .where(
            or_(
                ComplaintModel.reported_id == user_id,
                ComplaintModel.reporter_id == user_id,
            )
        )
        .order_by(ComplaintModel.created_at.desc(), ComplaintModel.complaint_id)
    )
    nps = (
        select(NpsResponseModel)
        .where(
            NpsResponseModel.user_id == user_id,
            NpsResponseModel.score.between(1, 5),
        )
        .order_by(NpsResponseModel.created_at.desc(), NpsResponseModel.id)
    )
    rater = aliased(UserModel)
    recipient = aliased(UserModel)
    ratings = (
        select(
            BloggerRatingModel,
            rater.username,
            OrderModel.offer_text,
            recipient.username,
        )
        .join(recipient, recipient.user_id == BloggerRatingModel.blogger_id)
        .join(rater, rater.user_id == BloggerRatingModel.rater_id)
        .join(OrderModel, OrderModel.order_id == BloggerRatingModel.order_id)
        .where(
            or_(
                BloggerRatingModel.blogger_id == user_id,
                BloggerRatingModel.rater_id == user_id,
            )
        )
        .order_by(
            func.coalesce(
                BloggerRatingModel.updated_at, BloggerRatingModel.created_at
            ).desc(),
            BloggerRatingModel.rating_id,
        )
    )
    orders = (
        select(OrderModel)
        .where(
            OrderModel.advertiser_id == user_id, *worklist_conditions("all", "")
        )
        .order_by(OrderModel.created_at.desc(), OrderModel.order_id)
    )

    queries = {
        "feedback": _interaction_feedback(user_id),
        "complaints": complaints,
        "nps": nps,
        "ratings": ratings,
    }
    if is_customer:
        queries["orders"] = orders
    for name, query in queries.items():
        page = pages.get(name, 1)
        result = await session.execute(
            query.offset((page - 1) * PROFILE_HISTORY_PAGE_SIZE).limit(
                PROFILE_HISTORY_PAGE_SIZE + 1
            )
        )
        rows = result.all()
        history[name] = {
            "items": rows[:PROFILE_HISTORY_PAGE_SIZE],
            "page": page,
            "has_next": len(rows) > PROFILE_HISTORY_PAGE_SIZE,
        }

    if is_creator:
        rating = await SqlAlchemyBloggerRatingRepository(
            session_factory
        ).get_avg_rating(user_id, session=session)
        responses = await session.execute(
            select(func.count())
            .select_from(OfferDispatchModel)
            .where(
                OfferDispatchModel.blogger_id == user_id,
                OfferDispatchModel.accepted.is_not(None),
            )
        )
        history["creator_rating"] = rating
        history["responses"] = int(responses.scalar() or 0)
    return history
