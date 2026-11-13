"""Read-only operational metrics from existing order and creator history."""

from datetime import datetime

from sqlalchemy import case, distinct, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.admin.order_worklist import business_order_conditions
from ugc_bot.domain.enums import PaymentStatus, UserStatus
from ugc_bot.infrastructure.db.collaboration_models import (
    CollaborationEventModel,
    CollaborationModel,
)
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    OfferDispatchModel,
    OrderModel,
    PaymentModel,
    UserModel,
)


async def creator_metrics(
    session: AsyncSession, start: datetime, end: datetime
) -> dict[str, int]:
    # Count accepted offers and recorded starts of paid collaborations.
    activity = union_all(
        select(
            OfferDispatchModel.blogger_id.label("creator"),
            func.coalesce(
                OfferDispatchModel.updated_at, OfferDispatchModel.created_at
            ).label("at"),
        )
        .join(OrderModel, OrderModel.order_id == OfferDispatchModel.order_id)
        .where(
            OfferDispatchModel.accepted.is_(True),
            OfferDispatchModel.in_offer.is_(True),
            OrderModel.financial_version.is_(None)
            | OrderModel.complimentary.is_(True),
            *business_order_conditions(),
        ),
        select(
            CollaborationModel.creator_id, CollaborationEventModel.occurred_at
        )
        .join(
            CollaborationModel,
            CollaborationModel.assignment_id
            == CollaborationEventModel.assignment_id,
        )
        .join(OrderModel, OrderModel.order_id == CollaborationModel.order_id)
        .where(
            CollaborationEventModel.event_type
            == "financial.collaboration.started",
            *business_order_conditions(),
        ),
    ).subquery()
    total = func.count(distinct(UserModel.user_id))
    has_telegram = func.nullif(func.trim(UserModel.telegram_id), "").is_not(
        None
    )
    stats = (
        await session.execute(
            select(
                total.label("profiles"),
                total.filter(has_telegram).label("telegram"),
                total.filter(
                    has_telegram, UserModel.status == UserStatus.BOT_BLOCKED
                ).label("bot_blocked"),
                func.count(distinct(activity.c.creator)).label("ever_worked"),
                func.count(distinct(activity.c.creator))
                .filter(activity.c.at >= start, activity.c.at < end)
                .label("worked_period"),
            )
            .select_from(BloggerProfileModel)
            .join(UserModel, UserModel.user_id == BloggerProfileModel.user_id)
            .outerjoin(activity, activity.c.creator == UserModel.user_id)
            .where(UserModel.status != UserStatus.DELETED)
        )
    ).one_or_none()
    return dict(stats._mapping) if stats else {}


async def order_conversion(
    session: AsyncSession, start: datetime, end: datetime
) -> dict[str, int | float | None]:
    paid_at = func.coalesce(PaymentModel.paid_at, PaymentModel.created_at)
    paid = (
        select(PaymentModel.payment_id)
        .where(
            PaymentModel.order_id == OrderModel.order_id,
            PaymentModel.status == PaymentStatus.PAID,
            paid_at >= OrderModel.created_at,
            paid_at < end,
        )
        .correlate(OrderModel)
        .exists()
    )
    query = select(
        func.count(OrderModel.order_id),
        func.count(case((paid, 1))),
    ).where(
        *business_order_conditions(),
        OrderModel.complimentary.is_(False),
        OrderModel.created_at >= start,
        OrderModel.created_at < end,
    )
    row = (await session.execute(query)).one_or_none()
    created, converted = row if row else (0, 0)
    return {
        "created": created,
        "paid": converted,
        "percent": round(100 * converted / created, 1) if created else None,
    }
