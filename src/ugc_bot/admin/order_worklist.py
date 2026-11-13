"""Queries and single-order actions for the SQLAdmin orders list."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import String, cast, false, or_, select, text
from sqlalchemy.orm import InstrumentedAttribute, Session

from ugc_bot.domain.enums import AuditAction, OrderStatus, PaymentStatus
from ugc_bot.infrastructure.db.checkout_models import CHECKOUTS, INBOX
from ugc_bot.infrastructure.db.dispatch_control import CONTROLS
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    BloggerRatingModel,
    ComplaintModel,
    InteractionModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderModel,
    OutboxEventModel,
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
_TEST_ORDER_ENTITY = "order_test_marker"
UNPAID_GROUP = "unpaid"


def _without_payment():
    return (
        ~select(PaymentModel.payment_id)
        .where(PaymentModel.order_id == OrderModel.order_id)
        .correlate(OrderModel)
        .exists()
    )


def _without_order_activity():
    return _without_payment() & ~or_(
        *(
            select(table.c.order_id)
            .where(table.c.order_id == OrderModel.order_id)
            .correlate(OrderModel)
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


def _can_hide():
    return (OrderModel.status == OrderStatus.NEW) & _without_order_activity()


def _can_close():
    return (
        (OrderModel.status == OrderStatus.ACTIVE)
        & OrderModel.financial_version.is_(None)
        & _without_payment()
    )


def _is_test_order():
    return (
        select(AuditLogModel.new_values["test"].as_boolean())
        .where(
            AuditLogModel.entity_type == _TEST_ORDER_ENTITY,
            AuditLogModel.entity_id == OrderModel.order_id,
        )
        .order_by(AuditLogModel.changed_at.desc(), AuditLogModel.id.desc())
        .limit(1)
        .correlate(OrderModel)
        .scalar_subquery()
        .is_(True)
    )


def business_order_conditions():
    return (*worklist_conditions("all", ""), ~_is_test_order())


def can_delete_order(*, postgresql: bool):
    eligible = (
        OrderModel.status.in_((OrderStatus.NEW, OrderStatus.PENDING_MODERATION))
        & _without_order_activity()
        & OrderModel.complimentary.is_(False)
        & ~select(INBOX.c.order_id)
        .where(INBOX.c.order_id == OrderModel.order_id)
        .correlate(OrderModel)
        .exists()
        & ~select(CONTROLS.c.order_id)
        .where(CONTROLS.c.order_id == OrderModel.order_id)
        .correlate(OrderModel)
        .exists()
    )
    if not postgresql:
        return eligible
    return (
        eligible
        & ~select(OutboxEventModel.event_id)
        .where(
            OutboxEventModel.aggregate_id == cast(OrderModel.order_id, String),
            OutboxEventModel.event_type == "order.activated",
        )
        .correlate(OrderModel)
        .exists()
    )


def _latest_visibility_event(order_id: UUID | InstrumentedAttribute[UUID]):
    return (
        select(AuditLogModel)
        .where(
            AuditLogModel.entity_type == _VISIBILITY_ENTITY,
            AuditLogModel.entity_id == order_id,
        )
        .order_by(AuditLogModel.changed_at.desc(), AuditLogModel.id.desc())
        .limit(1)
    )


def aging_unpaid_condition(now: datetime, hours: int):
    paid = (
        select(PaymentModel.payment_id)
        .where(
            PaymentModel.order_id == OrderModel.order_id,
            or_(
                PaymentModel.status == PaymentStatus.PAID,
                PaymentModel.paid_at.is_not(None),
                PaymentModel.captured_minor > 0,
            ),
        )
        .correlate(OrderModel)
        .exists()
    )
    return (
        (OrderModel.status == OrderStatus.NEW)
        & (OrderModel.created_at <= now - timedelta(hours=hours))
        & ~paid
        & ~_is_test_order()
    )


def order_visibility():
    return (
        _latest_visibility_event(OrderModel.order_id)
        .with_only_columns(AuditLogModel.new_values["visible"].as_boolean())
        .correlate(OrderModel)
        .scalar_subquery()
    )


def worklist_conditions(group: str, status: str):
    # A hidden legacy order can still receive payment and resurface.
    hidden = _can_hide() & order_visibility().is_(False)
    if group == "hidden":
        return [hidden]

    conditions = [
        OrderModel.status != OrderStatus.DELETED,
        ~hidden,
    ]
    if group == "closed":
        conditions.append(OrderModel.status == OrderStatus.CLOSED)
    elif group == "test":
        conditions.append(_is_test_order())
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
            _is_test_order().label("is_test"),
            can_delete_order(
                postgresql=session.get_bind().dialect.name == "postgresql"
            ).label("can_delete"),
            CONTROLS.c.paused.label("dispatch_paused"),
        )
        .select_from(OrderModel)
        .outerjoin(CONTROLS, CONTROLS.c.order_id == OrderModel.order_id)
        .outerjoin(UserModel, UserModel.user_id == OrderModel.advertiser_id)
        .outerjoin(
            AdvertiserProfileModel,
            AdvertiserProfileModel.user_id == OrderModel.advertiser_id,
        )
        .where(OrderModel.order_id.in_(order_ids))
    )
    return {row.order_id: row for row in rows}


def _mark_test_order(session: Session, order_id: UUID, marked: bool) -> str:
    eligible, was_marked = session.execute(
        select(_can_hide(), _is_test_order()).where(
            OrderModel.order_id == order_id
        )
    ).one()
    if marked and not eligible:
        return "Отметить можно только черновик без оплаты и связанных действий."
    if was_marked != marked:
        session.add(
            AuditLogModel(
                entity_type=_TEST_ORDER_ENTITY,
                entity_id=order_id,
                action=AuditAction.UPDATE,
                old_values={"test": was_marked},
                new_values={"test": marked},
            )
        )
    return (
        "Заказ отмечен как тестовый." if marked else "Тестовая отметка снята."
    )


def _delete_order(
    session: Session, order: OrderModel, *, test_only: bool
) -> str:
    eligible = can_delete_order(
        postgresql=session.get_bind().dialect.name == "postgresql"
    )
    if test_only:
        eligible = eligible & _is_test_order()
    if not session.scalar(
        select(eligible).where(OrderModel.order_id == order.order_id)
    ):
        return (
            "Удалить можно только тестовый черновик "
            "без оплаты и связанных действий."
            if test_only
            else "Удалить можно только заказ без оплаты, "
            "рассылки и связанных действий."
        )
    previous_status = order.status.value
    order.status = OrderStatus.DELETED
    order.dispatch_stopped = True
    order.updated_at = datetime.now(timezone.utc)
    values: dict[str, str | bool] = {"status": OrderStatus.DELETED.value}
    if test_only:
        values["test"] = True
    session.add(
        AuditLogModel(
            entity_type="order",
            entity_id=order.order_id,
            action=AuditAction.DELETE,
            old_values={"status": previous_status},
            new_values=values,
        )
    )
    return (
        "Тестовый заказ удалён."
        if test_only
        else "Заказ удалён. История сохранена."
    )


def _set_order_visibility(
    session: Session, order_id: UUID, visible: bool
) -> str:
    if not visible and not session.scalar(
        select(_can_hide()).where(OrderModel.order_id == order_id)
    ):
        return "Заказ уже в работе или связан с оплатой. Скрытие недоступно."
    previous = session.scalar(_latest_visibility_event(order_id))
    was_visible = (
        previous is None or previous.new_values.get("visible") is not False
    )
    if was_visible != visible:
        changed_at = datetime.now(timezone.utc)
        if previous is not None:
            # Keep event order when app clocks differ or timestamps tie.
            last_change = previous.changed_at
            if last_change.tzinfo is None:
                last_change = last_change.replace(tzinfo=timezone.utc)
            changed_at = max(
                changed_at, last_change + timedelta(microseconds=1)
            )
        session.add(
            AuditLogModel(
                entity_type=_VISIBILITY_ENTITY,
                entity_id=order_id,
                action=AuditAction.UPDATE,
                old_values={"visible": was_visible},
                new_values={"visible": visible},
                changed_at=changed_at,
            )
        )
    return "Заказ возвращён в список." if visible else "Заказ убран из списка."


def change_order_worklist(
    session: Session, order_id: UUID, operation: str
) -> str:
    if (
        operation in {"delete", "delete-test"}
        and session.get_bind().dialect.name == "postgresql"
    ):
        # Use the same lock order as native checkout and customer cancellation.
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": str(order_id)},
        )
    order = session.get(OrderModel, order_id, with_for_update=True)
    if order is None or order.status == OrderStatus.DELETED:
        return "Заказ не найден."
    if operation in {"mark-test", "unmark-test"}:
        return _mark_test_order(session, order_id, operation == "mark-test")
    if operation in {"delete", "delete-test"}:
        return _delete_order(
            session, order, test_only=operation == "delete-test"
        )
    if operation in {"hide", "restore"}:
        return _set_order_visibility(session, order_id, operation == "restore")
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
