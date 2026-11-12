"""Queries and single-order actions for the SQLAdmin orders list."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import String, cast, false, or_, select
from sqlalchemy.orm import Session

from ugc_bot.domain.enums import AuditAction, OrderStatus
from ugc_bot.infrastructure.db.checkout_models import CHECKOUTS
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    BloggerRatingModel,
    ComplaintModel,
    InteractionModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_intake_models import ACCOMPANIMENT_LEADS

ORDER_STATUS_LABELS = {
    OrderStatus.NEW: "Новый",
    OrderStatus.PENDING_MODERATION: "На модерации",
    OrderStatus.ACTIVE: "Активный",
    OrderStatus.CLOSED: "Закрытый",
}
_VISIBILITY_ENTITY = "order_worklist_visibility"


def _without_payment():
    return (
        ~select(PaymentModel.payment_id)
        .where(PaymentModel.order_id == OrderModel.order_id)
        .exists()
    )


def _can_hide():
    return (
        (OrderModel.status == OrderStatus.NEW)
        & _without_payment()
        & ~or_(
            *(
                select(table.c.order_id)
                .where(table.c.order_id == OrderModel.order_id)
                .exists()
                for table in (
                    CHECKOUTS,
                    ACCOMPANIMENT_LEADS,
                    OfferDispatchModel.__table__,
                    BloggerRatingModel.__table__,
                    InteractionModel.__table__,
                    ManagerOrderModel.__table__,
                    ComplaintModel.__table__,
                )
            )
        )
    )


def _can_close():
    return (
        (OrderModel.status == OrderStatus.ACTIVE)
        & OrderModel.financial_version.is_(None)
        & _without_payment()
    )


def _has_hide_record():
    return (
        select(AuditLogModel.id)
        .where(
            AuditLogModel.entity_type == _VISIBILITY_ENTITY,
            AuditLogModel.entity_id == OrderModel.order_id,
        )
        .exists()
    )


def worklist_conditions(group: str, status: str):
    conditions = [
        OrderModel.status != OrderStatus.DELETED,
        # A legacy invoice can be in flight before a payment row exists.
        # A list-only hide lets the normal checkout proceed and resurface.
        ~(_can_hide() & _has_hide_record()),
    ]
    if group == "closed":
        conditions.append(OrderModel.status == OrderStatus.CLOSED)
    elif group != "all":
        conditions.append(OrderModel.status != OrderStatus.CLOSED)
    if status in ORDER_STATUS_LABELS:
        conditions.append(OrderModel.status == status)
    return conditions


def search_orders(term: str):
    term = term.strip()
    try:
        order_id = UUID(term)
    except ValueError:
        order_id = None
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return or_(
        *(
            column.ilike(pattern, escape="\\")
            for column in (
                OrderModel.offer_text,
                OrderModel.barter_description,
                OrderModel.product_link,
                OrderModel.geography,
                OrderModel.brief_link,
                cast(OrderModel.order_id, String),
            )
        ),
        OrderModel.order_id == order_id if order_id is not None else false(),
        select(UserModel.user_id)
        .where(
            UserModel.user_id == OrderModel.advertiser_id,
            or_(
                UserModel.username.ilike(pattern, escape="\\"),
                UserModel.telegram.ilike(pattern, escape="\\"),
            ),
        )
        .exists(),
        select(AdvertiserProfileModel.user_id)
        .where(
            AdvertiserProfileModel.user_id == OrderModel.advertiser_id,
            AdvertiserProfileModel.brand.ilike(pattern, escape="\\"),
        )
        .exists(),
    )


def worklist_row_details(session: Session, order_ids: list[UUID]):
    if not order_ids:
        return {}
    rows = session.execute(
        select(
            OrderModel.order_id,
            UserModel.username,
            AdvertiserProfileModel.brand,
            _can_close().label("can_close"),
            _can_hide().label("can_hide"),
        )
        .select_from(OrderModel)
        .outerjoin(UserModel, UserModel.user_id == OrderModel.advertiser_id)
        .outerjoin(
            AdvertiserProfileModel,
            AdvertiserProfileModel.user_id == OrderModel.advertiser_id,
        )
        .where(OrderModel.order_id.in_(order_ids))
    )
    return {row.order_id: row for row in rows}


def change_order_worklist(
    session: Session, order_id: UUID, operation: str
) -> str:
    order = session.get(OrderModel, order_id, with_for_update=True)
    if order is None:
        return "Заказ не найден."
    if operation == "hide":
        if not session.scalar(
            select(_can_hide()).where(OrderModel.order_id == order_id)
        ):
            return (
                "Заказ уже в работе или связан с оплатой. Скрытие недоступно."
            )
        if not session.scalar(
            select(_has_hide_record()).where(OrderModel.order_id == order_id)
        ):
            session.add(
                AuditLogModel(
                    entity_type=_VISIBILITY_ENTITY,
                    entity_id=order_id,
                    action=AuditAction.UPDATE,
                    old_values={"visible": True},
                    new_values={"visible": False},
                )
            )
        return "Заказ убран из списка."
    if not session.scalar(
        select(_can_close()).where(OrderModel.order_id == order_id)
    ):
        return "Закрыть здесь можно только активный заказ без оплаты."

    now = datetime.now(timezone.utc)
    order.status = OrderStatus.CLOSED
    order.dispatch_stopped = True
    order.completed_at = now
    order.updated_at = now
    session.add(
        AuditLogModel(
            entity_type="order",
            entity_id=order_id,
            action=AuditAction.UPDATE,
            old_values={"status": OrderStatus.ACTIVE.value},
            new_values={"status": OrderStatus.CLOSED.value},
        )
    )
    return "Заказ закрыт."
