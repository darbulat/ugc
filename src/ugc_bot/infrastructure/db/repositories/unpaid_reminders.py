"""Select eligible reminders and keep delivery facts in the admin audit log."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, aliased

from ugc_bot.admin.order_worklist import (
    aging_unpaid_condition,
    order_visibility,
)
from ugc_bot.domain.enums import AuditAction, MessengerType, UserStatus
from ugc_bot.infrastructure.db.customer_workflow_models import JOBS, SERIES
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.reminder_coordination import (
    CLIENT_REMINDER,
    MOSCOW,
    ORDER_REMINDER,
    lock_customer_reminders,
    moscow_day_start,
)
from ugc_bot.infrastructure.db.repositories.customer_workflows import (
    SqlAlchemyCustomerWorkflowRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
)


def in_send_window(at: datetime) -> bool:
    return 10 <= at.astimezone(MOSCOW).hour < 19


def _recent_audit(entity_type: str, entity_id, since: datetime | None = None):
    event = aliased(AuditLogModel)
    query = select(event.id).where(
        event.entity_type == entity_type, event.entity_id == entity_id
    )
    if since is not None:
        query = query.where(event.changed_at >= since)
    return query.exists()


def _candidate_query(
    at: datetime, start_at: datetime, excluded: frozenset[UUID]
):
    day_start = moscow_day_start(at)
    followup = (
        select(JOBS.c.job_id)
        .where(
            JOBS.c.recipient_id == UserModel.user_id,
            JOBS.c.series_id.is_not(None),
            JOBS.c.state.in_(("sending", "accepted", "unknown")),
            JOBS.c.lease_until >= day_start,
        )
        .exists()
    )
    return (
        select(
            OrderModel,
            UserModel,
            AdvertiserProfileModel.brand,
            _recent_audit(ORDER_REMINDER, OrderModel.order_id).label(
                "attempted"
            ),
        )
        .join(UserModel, UserModel.user_id == OrderModel.advertiser_id)
        .join(
            AdvertiserProfileModel,
            AdvertiserProfileModel.user_id == UserModel.user_id,
        )
        .where(
            aging_unpaid_condition(at, 24),
            order_visibility().is_not(False),
            OrderModel.created_at >= start_at,
            OrderModel.complimentary.is_(False),
            OrderModel.dispatch_stopped.is_(False),
            UserModel.messenger_type == MessengerType.TELEGRAM,
            UserModel.telegram_id.op("~")(r"^[1-9][0-9]{0,15}$"),
            UserModel.status == UserStatus.ACTIVE,
            UserModel.admin.is_(False),
            UserModel.role_chosen_at.is_not(None),
            UserModel.user_id.not_in(excluded),
            or_(
                UserModel.last_role_reminder_at.is_(None),
                UserModel.last_role_reminder_at < day_start,
            ),
            ~select(SERIES.c.series_id)
            .where(
                SERIES.c.user_id == UserModel.user_id,
                SERIES.c.opted_out.is_(True),
            )
            .exists(),
            ~followup,
            ~_recent_audit(
                CLIENT_REMINDER, UserModel.user_id, at - timedelta(hours=24)
            ),
        )
        .order_by(OrderModel.created_at.desc(), OrderModel.order_id)
    )


async def list_candidates(
    session: AsyncSession,
    at: datetime,
    start_at: datetime,
    excluded: frozenset[UUID],
    *,
    user_id: UUID | None = None,
) -> list[tuple[OrderModel, UserModel, str | None]]:
    query = _candidate_query(at, start_at, excluded)
    if user_id is not None:
        query = query.where(UserModel.user_id == user_id)
    rows = await session.execute(query)
    workflow = SqlAlchemyCustomerWorkflowRepository()
    candidates: list[tuple[OrderModel, UserModel, str | None]] = []
    seen: set[UUID] = set()
    for order, user, brand, attempted in rows:
        if user.user_id in seen:
            continue
        if (
            await workflow.payment_state(order.order_id, session=session)
            == "unpaid"
        ):
            seen.add(user.user_id)
            if not attempted:
                candidates.append((order, user, brand))
    return candidates


async def reserve(
    session: AsyncSession,
    order_id: UUID,
    user_id: UUID,
    at: datetime,
    start_at: datetime,
    excluded: frozenset[UUID],
) -> str | None:
    await lock_customer_reminders(session, user_id)
    await session.scalar(
        select(UserModel.user_id)
        .where(UserModel.user_id == user_id)
        .with_for_update()
    )
    await SqlAlchemyFinancialItemRepository().lock_order(
        order_id, session=session
    )
    await session.scalar(
        select(OrderModel.order_id)
        .where(OrderModel.order_id == order_id)
        .with_for_update()
    )
    if not in_send_window(at):
        return None
    # Re-select the freshest payable candidate after acquiring the locks.
    candidates = await list_candidates(
        session, at, start_at, excluded, user_id=user_id
    )
    if not candidates or candidates[0][0].order_id != order_id:
        return None
    for entity_type, entity_id in (
        (ORDER_REMINDER, order_id),
        (CLIENT_REMINDER, user_id),
    ):
        session.add(
            AuditLogModel(
                entity_type=entity_type,
                entity_id=entity_id,
                action=AuditAction.CREATE,
                changed_at=at,
                new_values={"state": "sending"},
            )
        )
    return candidates[0][1].telegram_id


async def finish(
    session: AsyncSession,
    order_id: UUID,
    at: datetime,
    state: str,
    reference: str | None,
) -> None:
    session.add(
        AuditLogModel(
            entity_type=ORDER_REMINDER,
            entity_id=order_id,
            action=AuditAction.UPDATE,
            changed_at=at,
            new_values={"state": state, "reference": reference},
        )
    )


def reminder_statuses(session: Session, ids: list[UUID]):
    if not ids:
        return {}
    latest = (
        select(
            AuditLogModel.entity_id,
            AuditLogModel.new_values,
            AuditLogModel.changed_at,
            func.row_number()
            .over(
                partition_by=AuditLogModel.entity_id,
                order_by=(
                    AuditLogModel.changed_at.desc(),
                    AuditLogModel.action.desc(),
                    AuditLogModel.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(
            AuditLogModel.entity_type == ORDER_REMINDER,
            AuditLogModel.entity_id.in_(ids),
        )
        .subquery()
    )
    return {
        row.entity_id: (row.new_values["state"], row.changed_at)
        for row in session.execute(select(latest).where(latest.c.position == 1))
    }
