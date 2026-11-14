"""Read-only progress, activity, and manager summaries for the orders UI."""

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import case, func, select, union, union_all

from ugc_bot.domain.enums import OrderStatus
from ugc_bot.domain.social import SocialPlatform
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel
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
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


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


def picked_order_count():
    positions = (
        select(func.count())
        .select_from(ItemAssignmentModel)
        .join(
            OrderItemModel,
            OrderItemModel.paid_item_id == ItemAssignmentModel.paid_item_id,
        )
        .where(
            OrderItemModel.order_id == OrderModel.order_id,
            ItemAssignmentModel.valid_to.is_(None),
        )
        .correlate(OrderModel)
        .scalar_subquery()
    )
    responses = (
        select(func.count())
        .select_from(OfferDispatchModel)
        .where(
            OfferDispatchModel.order_id == OrderModel.order_id,
            OfferDispatchModel.in_offer.is_(True),
        )
        .correlate(OrderModel)
        .scalar_subquery()
    )
    return case(
        (use_financial_positions(), positions),
        else_=responses,
    )


def use_financial_positions():
    return OrderModel.financial_version.is_not(
        None
    ) & OrderModel.complimentary.is_(False)


def order_managers_query(order_ids):
    assignments = union(
        select(
            ManagerOrderModel.order_id,
            ManagerOrderModel.user_id.label("user_id"),
        ).where(ManagerOrderModel.order_id.in_(order_ids)),
        select(OrderItemModel.order_id, ItemAssignmentModel.manager_id)
        .join(
            OrderItemModel,
            OrderItemModel.paid_item_id == ItemAssignmentModel.paid_item_id,
        )
        .where(
            OrderItemModel.order_id.in_(order_ids),
            ItemAssignmentModel.valid_to.is_(None),
            ItemAssignmentModel.manager_id.is_not(None),
        ),
        select(OfferDispatchModel.order_id, OfferDispatchModel.manager_id)
        .join(OrderModel, OrderModel.order_id == OfferDispatchModel.order_id)
        .where(
            OfferDispatchModel.order_id.in_(order_ids),
            OfferDispatchModel.in_offer.is_(True),
            OfferDispatchModel.manager_id.is_not(None),
            ~use_financial_positions(),
        ),
    ).subquery()
    return (
        select(
            assignments.c.order_id,
            UserModel.user_id,
            UserModel.username,
            UserModel.telegram,
        )
        .join(UserModel, UserModel.user_id == assignments.c.user_id)
        .order_by(UserModel.username, UserModel.user_id)
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
    social_url = (
        select(SocialAccountModel.url)
        .where(
            SocialAccountModel.user_id == UserModel.user_id,
            SocialAccountModel.platform == SocialPlatform.INSTAGRAM,
        )
        .correlate(UserModel)
        .scalar_subquery()
    )
    instagram = (
        func.coalesce(
            social_url,
            (
                select(BloggerProfileModel.instagram_url)
                .where(BloggerProfileModel.user_id == UserModel.user_id)
                .correlate(UserModel)
                .scalar_subquery()
            ),
        )
        if session.get_bind().dialect.name == "postgresql"
        else social_url
    )
    rows = await session.execute(
        select(
            UserModel.user_id,
            UserModel.username,
            UserModel.telegram,
            instagram.label("instagram"),
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
