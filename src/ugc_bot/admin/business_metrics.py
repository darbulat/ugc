"""Read-only operational metrics from existing order and creator history."""

from datetime import datetime, timedelta
from typing import TypedDict

from sqlalchemy import (
    and_,
    case,
    distinct,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.admin.order_summary import use_financial_positions
from ugc_bot.admin.order_worklist import business_order_conditions
from ugc_bot.domain.enums import OrderStatus, PaymentStatus, UserStatus
from ugc_bot.infrastructure.db.collaboration_models import (
    CollaborationEventModel,
    CollaborationModel,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    BloggerProfileModel,
    ItemAssignmentModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    PaymentModel,
    UserModel,
)

# These are the shop's own requester accounts for orders launched before the
# admin workflow began recording complimentary activations.
_ADMIN_ORDER_ACCOUNTS = ("kamil_bakhteev", "usemycontent")


def _legacy_creator_picks():
    return (
        select(OfferDispatchModel.blogger_id.label("creator"))
        .join(OrderModel, OrderModel.order_id == OfferDispatchModel.order_id)
        .where(
            OfferDispatchModel.in_offer.is_(True),
            ~use_financial_positions(),
            *business_order_conditions(),
        )
    )


async def count_picked_creators(session: AsyncSession) -> int:
    paid_assignments = (
        select(ItemAssignmentModel.creator_id)
        .join(
            OrderItemModel,
            OrderItemModel.paid_item_id == ItemAssignmentModel.paid_item_id,
        )
        .join(OrderModel, OrderModel.order_id == OrderItemModel.order_id)
        .where(use_financial_positions(), *business_order_conditions())
    )
    picks = _legacy_creator_picks().union(paid_assignments).subquery()
    result = await session.execute(select(func.count()).select_from(picks))
    return int(result.scalar() or 0)


def _creator_order_activity():
    # Legacy offer dates use the latest edit time and are approximate.
    legacy = (
        _legacy_creator_picks()
        .add_columns(
            func.coalesce(
                OfferDispatchModel.updated_at, OfferDispatchModel.created_at
            ).label("at"),
            literal(True).label("legacy"),
        )
        .where(OfferDispatchModel.accepted.is_(True))
    )
    paid = (
        select(
            CollaborationModel.creator_id,
            CollaborationEventModel.occurred_at,
            literal(False),
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
            use_financial_positions(),
            *business_order_conditions(),
        )
    )
    return union_all(legacy, paid).subquery()


async def creator_metrics(
    session: AsyncSession, start: datetime, end: datetime
) -> dict[str, int]:
    activity = _creator_order_activity()
    in_period = and_(activity.c.at >= start, activity.c.at < end)
    by_creator = (
        select(
            activity.c.creator,
            func.min(activity.c.at).label("first_at"),
            func.count().filter(in_period).label("events"),
            func.count()
            .filter(in_period, activity.c.legacy.is_(True))
            .label("legacy"),
            func.count()
            .filter(in_period, activity.c.legacy.is_(False))
            .label("paid"),
        )
        .group_by(activity.c.creator)
        .subquery()
    )
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
                func.count(by_creator.c.creator).label("ever_worked"),
                func.count()
                .filter(by_creator.c.events > 0)
                .label("worked_period"),
                func.count()
                .filter(by_creator.c.events > 0, by_creator.c.first_at >= start)
                .label("first_period"),
                func.count()
                .filter(by_creator.c.events > 0, by_creator.c.first_at < start)
                .label("returning_period"),
                func.count()
                .filter(by_creator.c.legacy > 0)
                .label("legacy_period"),
                func.count()
                .filter(by_creator.c.paid > 0)
                .label("paid_started_period"),
            )
            .select_from(BloggerProfileModel)
            .join(UserModel, UserModel.user_id == BloggerProfileModel.user_id)
            .outerjoin(by_creator, by_creator.c.creator == UserModel.user_id)
            .where(UserModel.status != UserStatus.DELETED)
        )
    ).one_or_none()
    return dict(stats._mapping) if stats else {}


def _admin_requester_handle():
    telegram = func.lower(func.ltrim(func.trim(UserModel.telegram), "@"))
    username = func.lower(func.ltrim(func.trim(UserModel.username), "@"))
    return (
        select(
            case(
                (telegram.in_(_ADMIN_ORDER_ACCOUNTS), telegram),
                (username.in_(_ADMIN_ORDER_ACCOUNTS), username),
            )
        )
        .where(
            UserModel.user_id == OrderModel.advertiser_id,
            UserModel.admin.is_(True),
        )
        .correlate(OrderModel)
        .scalar_subquery()
    )


def _first_dispatch_at():
    return (
        select(func.min(OfferDispatchModel.created_at))
        .where(OfferDispatchModel.order_id == OrderModel.order_id)
        .correlate(OrderModel)
        .scalar_subquery()
    )


def _legacy_admin_launch(handle, first_dispatch):
    has_payment = (
        select(PaymentModel.payment_id)
        .where(PaymentModel.order_id == OrderModel.order_id)
        .correlate(OrderModel)
        .exists()
    )
    return and_(
        OrderModel.financial_version.is_(None),
        OrderModel.status.in_((OrderStatus.ACTIVE, OrderStatus.CLOSED)),
        handle.is_not(None),
        ~has_payment,
        first_dispatch.is_not(None),
    )


async def admin_launches(
    session: AsyncSession, start: datetime, end: datetime
) -> list[tuple[str | None, int]]:
    handle = _admin_requester_handle()
    first_dispatch = _first_dispatch_at()
    activation_at = (
        select(func.min(AuditLogModel.changed_at))
        .where(
            AuditLogModel.entity_type == "order",
            AuditLogModel.entity_id == OrderModel.order_id,
            AuditLogModel.new_values["complimentary"].as_boolean().is_(True),
        )
        .correlate(OrderModel)
        .scalar_subquery()
    )
    launched_at = func.coalesce(
        activation_at, first_dispatch, OrderModel.created_at
    )
    account = handle.label("account")
    query = (
        select(account, func.count().label("orders"))
        .select_from(OrderModel)
        .where(
            *business_order_conditions(),
            or_(
                OrderModel.complimentary.is_(True),
                _legacy_admin_launch(handle, first_dispatch),
            ),
            launched_at >= start,
            launched_at < end,
        )
        .group_by(account)
        .order_by(account)
    )
    result = await session.execute(query)
    return [(row.account, row.orders) for row in result.all()]


def _valid_order_payment_date(paid_at):
    # Manual entries can record a prepayment linked to the order.
    return or_(
        paid_at >= OrderModel.created_at, PaymentModel.provider == "manual"
    )


class CohortRate(TypedDict):
    eligible: int
    converted: int
    percent: float | None


class CohortMetrics(TypedDict):
    creator_activation: CohortRate
    customer_activation: CohortRate
    customer_repeat_90d: CohortRate
    customers_who_ordered_again: int
    repeat_customers: int
    paying_customers: int


def _cohort_rate(eligible: int, converted: int) -> CohortRate:
    return {
        "eligible": eligible,
        "converted": converted,
        "percent": round(100 * converted / eligible, 1) if eligible else None,
    }


def _activation_counts(first_event_at, as_of: datetime):
    registered_at = UserModel.created_at
    duration = timedelta(days=30)
    eligible = registered_at <= as_of - duration
    return (
        func.count().filter(eligible),
        func.count().filter(
            eligible,
            first_event_at >= registered_at,
            first_event_at < registered_at + duration,
        ),
    )


async def cohort_metrics(
    session: AsyncSession, as_of: datetime
) -> CohortMetrics:
    activity = _creator_order_activity()
    first_order = (
        select(activity.c.creator, func.min(activity.c.at).label("first_at"))
        .where(activity.c.at < as_of)
        .group_by(activity.c.creator)
        .subquery()
    )
    creator_counts = await session.execute(
        select(*_activation_counts(first_order.c.first_at, as_of))
        .select_from(BloggerProfileModel)
        .join(UserModel, UserModel.user_id == BloggerProfileModel.user_id)
        .outerjoin(first_order, first_order.c.creator == UserModel.user_id)
    )
    creator_eligible, creator_converted = creator_counts.one_or_none() or (0, 0)

    paid_at = func.coalesce(PaymentModel.paid_at, PaymentModel.created_at)
    # A single payment per order makes the rank an order rank.
    payment_order = (paid_at, OrderModel.order_id)
    paid_orders = (
        select(
            OrderModel.advertiser_id,
            OrderModel.order_id,
            paid_at.label("first_at"),
            func.lead(paid_at)
            .over(partition_by=OrderModel.advertiser_id, order_by=payment_order)
            .label("second_at"),
            func.row_number()
            .over(partition_by=OrderModel.advertiser_id, order_by=payment_order)
            .label("sequence"),
        )
        .select_from(PaymentModel)
        .join(OrderModel, OrderModel.order_id == PaymentModel.order_id)
        .where(
            *business_order_conditions(),
            OrderModel.complimentary.is_(False),
            PaymentModel.status == PaymentStatus.PAID,
            PaymentModel.amount > 0,
            _valid_order_payment_date(paid_at),
            paid_at < as_of,
        )
        .subquery()
    )
    paid_history = (
        select(paid_orders).where(paid_orders.c.sequence == 1).subquery()
    )
    ordered_again = (
        select(OrderModel.order_id)
        .where(
            OrderModel.advertiser_id == paid_history.c.advertiser_id,
            # A manually recorded prepayment can precede its own order.
            OrderModel.order_id != paid_history.c.order_id,
            OrderModel.created_at > paid_history.c.first_at,
            OrderModel.created_at < as_of,
            *_customer_application_conditions(),
        )
        .correlate(paid_history)
        .exists()
    )
    repeat_duration = timedelta(days=90)
    repeat_eligible = paid_history.c.first_at <= as_of - repeat_duration
    customer_counts = await session.execute(
        select(
            *_activation_counts(paid_history.c.first_at, as_of),
            func.count().filter(repeat_eligible),
            func.count().filter(
                repeat_eligible,
                paid_history.c.second_at
                < paid_history.c.first_at + repeat_duration,
            ),
            func.count().filter(ordered_again),
            func.count(paid_history.c.second_at),
            func.count(paid_history.c.first_at),
        )
        .select_from(AdvertiserProfileModel)
        .join(UserModel, UserModel.user_id == AdvertiserProfileModel.user_id)
        .join(
            paid_history,
            paid_history.c.advertiser_id == UserModel.user_id,
            full=True,
        )
    )
    (
        eligible,
        converted,
        repeat_base,
        repeat_90d,
        ordered_again_total,
        repeat_total,
        payers,
    ) = customer_counts.one_or_none() or (0, 0, 0, 0, 0, 0, 0)
    return {
        "creator_activation": _cohort_rate(creator_eligible, creator_converted),
        "customer_activation": _cohort_rate(eligible, converted),
        "customer_repeat_90d": _cohort_rate(repeat_base, repeat_90d),
        "customers_who_ordered_again": ordered_again_total,
        "repeat_customers": repeat_total,
        "paying_customers": payers,
    }


def _customer_application_conditions():
    return (
        *business_order_conditions(),
        OrderModel.complimentary.is_(False),
        ~_legacy_admin_launch(_admin_requester_handle(), _first_dispatch_at()),
    )


async def order_conversion(
    session: AsyncSession, start: datetime, end: datetime
) -> dict[str, int | float | None]:
    paid_at = func.coalesce(PaymentModel.paid_at, PaymentModel.created_at)
    paid = (
        select(PaymentModel.payment_id)
        .where(
            PaymentModel.order_id == OrderModel.order_id,
            PaymentModel.status == PaymentStatus.PAID,
            paid_at >= start,
            _valid_order_payment_date(paid_at),
            paid_at < end,
        )
        .correlate(OrderModel)
        .exists()
    )
    query = select(
        func.count(OrderModel.order_id),
        func.count(case((paid, 1))),
    ).where(
        *_customer_application_conditions(),
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
