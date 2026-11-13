"""Query filters and profile history for the admin directories."""

import re
from contextlib import suppress
from uuid import UUID

from sqlalchemy import func, not_, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement

from ugc_bot.admin.order_worklist import worklist_conditions
from ugc_bot.domain.enums import UserStatus
from ugc_bot.domain.social import SocialPlatform, normalize_social_url
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
)
from ugc_bot.infrastructure.db.repositories.ratings import (
    SqlAlchemyBloggerRatingRepository,
)

PROFILE_HISTORY_PAGE_SIZE = 10


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


def creator_directory_filters(
    q: str | None,
    city: str,
    status: str,
    followers_min: int | None,
    with_complaints: bool,
) -> list[ColumnElement[bool]]:
    filters = _person_search(q, BloggerProfileModel.instagram_url)
    filters.extend(_complaint_filter(with_complaints))
    if city.strip():
        filters.append(
            func.lower(func.trim(BloggerProfileModel.city))
            == city.strip().lower()
        )
    if status == "active":
        filters.append(UserModel.status == UserStatus.ACTIVE)
    elif status == "limited":
        filters.append(UserModel.status != UserStatus.ACTIVE)
    if followers_min is not None and followers_min >= 0:
        filters.append(
            BloggerProfileModel.instagram_followers_count >= followers_min
        )
    return filters


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
