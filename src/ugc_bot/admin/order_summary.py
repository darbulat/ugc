"""Read-only progress, activity, and manager summaries for the orders UI."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import and_, case, func, or_, select, union, union_all
from sqlalchemy.sql import ColumnElement

from ugc_bot.domain.enums import OrderStatus
from ugc_bot.domain.social import SocialPlatform
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel
from ugc_bot.infrastructure.db.instagram_maintenance_models import HEALTH
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ComplaintModel,
    InteractionModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_selection import (
    picked_order_count as picked_order_count,
)
from ugc_bot.infrastructure.db.order_selection import (
    use_financial_positions as use_financial_positions,
)
from ugc_bot.infrastructure.db.social_models import SocialAccountModel

ORDER_INACTIVITY_DAYS = 7


@dataclass(slots=True)
class DelayThresholds:
    """Thresholds for orders that need attention."""

    active_days: int
    no_responses_hours: int
    low_picked_hours: int
    archive_days: int


def order_age_hours(now: datetime, created_at: datetime) -> float:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return round((now - created_at).total_seconds() / 3600, 2)


def active_pick_reasons(
    now: datetime,
    order: OrderModel,
    picked: int,
    paused: bool | None,
    thresholds: DelayThresholds,
) -> list[str]:
    if (
        order.status != OrderStatus.ACTIVE
        or order.dispatch_stopped
        or picked >= order.bloggers_needed
    ):
        return []
    if paused:
        return ["dispatch_paused"]
    age = order_age_hours(now, order.created_at)
    reasons = []
    if age >= thresholds.active_days * 24:
        reasons.append("active_overdue")
    if not picked and age >= thresholds.no_responses_hours:
        reasons.append("no_responses")
    if (
        picked < min(3, order.bloggers_needed)
        and age >= thresholds.low_picked_hours
    ):
        reasons.append("low_picked")
    return reasons


def financial_positions(order_ids):
    return (
        select(
            OrderItemModel.order_id,
            ItemAssignmentModel.creator_id,
            ItemAssignmentModel.manager_id,
            ItemAssignmentModel.valid_from,
            CollaborationModel.state,
        )
        .join(
            OrderItemModel,
            OrderItemModel.paid_item_id == ItemAssignmentModel.paid_item_id,
        )
        .outerjoin(
            CollaborationModel,
            CollaborationModel.assignment_id
            == ItemAssignmentModel.assignment_id,
        )
        .where(
            OrderItemModel.order_id.in_(order_ids),
            ItemAssignmentModel.valid_to.is_(None),
        )
    )


def _manager_assignments():
    return union(
        select(
            ManagerOrderModel.order_id,
            ManagerOrderModel.user_id.label("user_id"),
        ),
        select(OrderItemModel.order_id, ItemAssignmentModel.manager_id)
        .join(
            OrderItemModel,
            OrderItemModel.paid_item_id == ItemAssignmentModel.paid_item_id,
        )
        .where(
            ItemAssignmentModel.valid_to.is_(None),
            ItemAssignmentModel.manager_id.is_not(None),
        ),
        select(OfferDispatchModel.order_id, OfferDispatchModel.manager_id)
        .join(OrderModel, OrderModel.order_id == OfferDispatchModel.order_id)
        .where(
            OfferDispatchModel.in_offer.is_(True),
            OfferDispatchModel.manager_id.is_not(None),
            ~use_financial_positions(),
        ),
    ).subquery()


def manager_display_name():
    """Use the required application name when the general profile is blank."""
    application_name = (
        select(
            func.nullif(
                func.trim(APPLICATIONS.c.answers["name"].as_string()), ""
            )
        )
        .where(APPLICATIONS.c.user_id == UserModel.user_id)
        .correlate(UserModel)
        .scalar_subquery()
    )
    return func.coalesce(
        func.nullif(func.trim(UserModel.username), ""), application_name
    )


def order_managers_query(order_ids):
    assignments = _manager_assignments()
    return (
        select(
            assignments.c.order_id,
            UserModel.user_id,
            manager_display_name().label("username"),
            UserModel.telegram,
        )
        .join(UserModel, UserModel.user_id == assignments.c.user_id)
        .where(assignments.c.order_id.in_(order_ids))
        .order_by(UserModel.username, UserModel.user_id)
    )


def order_has_manager() -> ColumnElement[bool]:
    assignments = _manager_assignments()
    return (
        select(1)
        .select_from(assignments)
        .join(UserModel, UserModel.user_id == assignments.c.user_id)
        .where(assignments.c.order_id == OrderModel.order_id)
        .correlate(OrderModel)
        .exists()
    )


def order_activity_at():
    sources = (
        (
            OfferDispatchModel,
            func.coalesce(
                OfferDispatchModel.updated_at, OfferDispatchModel.created_at
            ),
        ),
        (
            PaymentModel,
            func.coalesce(
                PaymentModel.paid_at,
                PaymentModel.updated_at,
                PaymentModel.created_at,
            ),
        ),
        (
            ManagerOrderModel,
            func.coalesce(
                ManagerOrderModel.updated_at, ManagerOrderModel.created_at
            ),
        ),
        (InteractionModel, InteractionModel.updated_at),
        (ComplaintModel, ComplaintModel.updated_at),
        (CollaborationModel, CollaborationModel.updated_at),
    )
    events = union_all(
        *(
            select(timestamp.label("at"))
            .where(model.order_id == OrderModel.order_id)
            .correlate(OrderModel)
            for model, timestamp in sources
        )
    ).subquery()
    return select(func.max(events.c.at)).correlate(OrderModel).scalar_subquery()


def order_is_inactive(now: datetime) -> ColumnElement[bool]:
    """Match the same order and related timestamps shown in the card."""
    cutoff = now - timedelta(days=ORDER_INACTIVITY_DAYS)
    return (
        (OrderModel.created_at <= cutoff)
        & (OrderModel.updated_at <= cutoff)
        & (
            func.coalesce(OrderModel.completed_at, OrderModel.created_at)
            <= cutoff
        )
        & (func.coalesce(order_activity_at(), OrderModel.created_at) <= cutoff)
    )


def latest_order_activity(
    order: OrderModel, related_at: datetime | None
) -> datetime:
    dates = (order.created_at, order.updated_at, order.completed_at, related_at)
    return max(
        date if date.tzinfo else date.replace(tzinfo=timezone.utc)
        for date in dates
        if date is not None
    )


def manager_contact(row) -> dict[str, str | None]:
    return {
        "id": str(row.user_id),
        "name": row.username or row.telegram,
        "telegram": row.telegram,
    }


def safe_order_link(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        url = urlsplit(value)
        if (
            url.scheme in {"http", "https"}
            and url.hostname
            and not (url.username or url.password)
        ):
            return value
    except ValueError:
        return None
    return None


async def order_creator_contacts(session, creator_ids):
    if not creator_ids:
        return {}
    if session.get_bind().dialect.name == "postgresql":
        return await _postgres_creator_contacts(session, creator_ids)
    social_url = (
        select(SocialAccountModel.url)
        .where(
            SocialAccountModel.user_id == UserModel.user_id,
            SocialAccountModel.platform == SocialPlatform.INSTAGRAM,
        )
        .correlate(UserModel)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(
            UserModel.user_id,
            UserModel.username,
            UserModel.telegram,
            social_url.label("instagram"),
        ).where(UserModel.user_id.in_(creator_ids))
    )
    return {
        str(row.user_id): {
            "name": row.username or row.telegram,
            "telegram": row.telegram,
            "instagram": row.instagram,
        }
        for row in rows.all()
    }


async def _postgres_creator_contacts(session, creator_ids):
    profile, social = BloggerProfileModel, SocialAccountModel
    same_verified_id = and_(
        profile.confirmed.is_(True),
        social.verified.is_(True),
        social.external_id == func.nullif(profile.instagram_user_id, ""),
    )
    newer_handle = and_(
        same_verified_id,
        func.lower(social.handle) != func.lower(profile.instagram_username),
        or_(
            profile.instagram_stats_fetched_at > social.metrics_fetched_at,
            and_(
                HEALTH.c.status == "healthy",
                HEALTH.c.handle == profile.instagram_username,
                HEALTH.c.last_success_at > social.verification_observed_at,
            ),
        ),
    )
    rows = await session.execute(
        select(
            UserModel.user_id,
            UserModel.username,
            UserModel.telegram,
            case(
                (newer_handle, profile.instagram_url),
                else_=func.coalesce(social.url, profile.instagram_url),
            ).label("instagram"),
            case(
                (HEALTH.c.status == "review", "review"),
                (HEALTH.c.status == "suspect", "suspect"),
                (newer_handle, "renamed"),
                (
                    and_(
                        same_verified_id,
                        func.lower(social.handle)
                        != func.lower(profile.instagram_username),
                    ),
                    "mismatch",
                ),
            ).label("instagram_status"),
        )
        .outerjoin(profile, profile.user_id == UserModel.user_id)
        .outerjoin(
            social,
            and_(
                social.user_id == UserModel.user_id,
                social.platform == SocialPlatform.INSTAGRAM,
            ),
        )
        .outerjoin(
            HEALTH,
            and_(
                HEALTH.c.user_id == UserModel.user_id,
                HEALTH.c.meta_id == profile.instagram_user_id,
            ),
        )
        .where(UserModel.user_id.in_(creator_ids))
    )
    return {
        str(row.user_id): {
            "name": row.username or row.telegram,
            "telegram": row.telegram,
            "instagram": row.instagram,
            "instagram_status": row.instagram_status,
        }
        for row in rows.all()
    }
