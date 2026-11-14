"""Queries and single-order actions for the SQLAdmin orders list."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import String, case, cast, false, or_, select, text
from sqlalchemy.orm import InstrumentedAttribute, Session

from ugc_bot.admin.complaints import OPEN_COMPLAINT_STATUSES
from ugc_bot.admin.order_summary import (
    DelayThresholds,
    active_pick_reasons,
    latest_order_activity,
    manager_contact,
    order_activity_at,
    order_managers_query,
    picked_order_count,
)
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
    OrderItemModel,
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
_ARCHIVE_ENTITY = "order_worklist_archive"
UNPAID_GROUP = "unpaid"


_ORDER_ACTIVITY = (
    (PaymentModel.__table__, "Есть запись об оплате"),
    (CHECKOUTS, "Создана платёжная сессия"),
    (ACCOMPANIMENT_LEADS, "Есть заявка на сопровождение"),
    (OfferDispatchModel.__table__, "Есть рассылка или отклики"),
    (BloggerRatingModel.__table__, "Есть оценки креаторов"),
    (InteractionModel.__table__, "Есть история работы с креаторами"),
    (ManagerOrderModel.__table__, "Назначен менеджер"),
    (ComplaintModel.__table__, "Есть жалобы по заказу"),
)


def _order_has(table):
    return (
        select(table.c.order_id)
        .where(table.c.order_id == OrderModel.order_id)
        .correlate(OrderModel)
        .exists()
    )


def _without_order_activity():
    return ~or_(*(_order_has(table) for table, _ in _ORDER_ACTIVITY))


def _can_hide():
    return (OrderModel.status == OrderStatus.NEW) & _without_order_activity()


def _can_close():
    return (
        (OrderModel.status == OrderStatus.ACTIVE)
        & OrderModel.financial_version.is_(None)
        & ~_order_has(PaymentModel.__table__)
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


def order_deletion_blocker(*, postgresql: bool):
    """Return the first reason the guarded test deletion would refuse."""
    checks = [
        (~_is_test_order(), "Заказ не отмечен как тестовый"),
        *((_order_has(table), label) for table, label in _ORDER_ACTIVITY),
        (_order_has(INBOX), "Есть событие оплаты"),
        (
            _order_has(OrderItemModel.__table__),
            "Есть оплачиваемые позиции заказа",
        ),
        (_order_has(CONTROLS), "Сохранены настройки рассылки"),
        (OrderModel.complimentary.is_(True), "Заказ запускался без оплаты"),
        (
            OrderModel.status.not_in(
                (OrderStatus.NEW, OrderStatus.PENDING_MODERATION)
            ),
            "Заказ уже вышел из черновиков",
        ),
    ]
    if postgresql:
        checks.append(
            (
                select(OutboxEventModel.event_id)
                .where(
                    OutboxEventModel.aggregate_id
                    == cast(OrderModel.order_id, String),
                    OutboxEventModel.event_type == "order.activated",
                )
                .correlate(OrderModel)
                .exists(),
                "Заказ запускался в рассылку",
            )
        )
    return case(*checks)


def _latest_worklist_event(
    order_id: UUID | InstrumentedAttribute[UUID], entity: str
):
    return (
        select(AuditLogModel)
        .where(
            AuditLogModel.entity_type == entity,
            AuditLogModel.entity_id == order_id,
        )
        .order_by(AuditLogModel.changed_at.desc(), AuditLogModel.id.desc())
        .limit(1)
    )


def order_archived():
    return (
        _latest_worklist_event(OrderModel.order_id, _ARCHIVE_ENTITY)
        .with_only_columns(AuditLogModel.new_values["archived"].as_boolean())
        .correlate(OrderModel)
        .scalar_subquery()
        .is_(True)
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
        _latest_worklist_event(OrderModel.order_id, _VISIBILITY_ENTITY)
        .with_only_columns(AuditLogModel.new_values["visible"].as_boolean())
        .correlate(OrderModel)
        .scalar_subquery()
    )


def worklist_conditions(group: str, status: str, *, admin_list: bool = False):
    if group == "removed":
        return [OrderModel.status != OrderStatus.DELETED, order_archived()]
    scope = [~order_archived()] if admin_list else []
    # A hidden legacy order can still receive payment and resurface.
    hidden = _can_hide() & order_visibility().is_(False)
    if group == "hidden":
        return [hidden, *scope]

    if group == "test":
        return [
            OrderModel.status != OrderStatus.DELETED,
            _is_test_order(),
            *scope,
        ]

    conditions = [OrderModel.status != OrderStatus.DELETED, ~hidden, *scope]
    if group != "all":
        conditions.append(~_is_test_order())
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


def worklist_row_details(
    session: Session, order_ids: list[UUID], thresholds: DelayThresholds
):
    if not order_ids:
        return {}
    managers = defaultdict(list)
    for manager in session.execute(order_managers_query(order_ids)):
        managers[manager.order_id].append(manager_contact(manager))
    rows = session.execute(
        select(
            OrderModel,
            picked_order_count().label("picked"),
            order_activity_at().label("related_at"),
            select(ComplaintModel.complaint_id)
            .where(
                ComplaintModel.order_id == OrderModel.order_id,
                ComplaintModel.status.in_(OPEN_COMPLAINT_STATUSES),
            )
            .correlate(OrderModel)
            .exists()
            .label("has_complaints"),
            UserModel.username,
            AdvertiserProfileModel.brand,
            _can_close().label("can_close"),
            _can_hide().label("can_hide"),
            _is_test_order().label("is_test"),
            order_deletion_blocker(
                postgresql=session.get_bind().dialect.name == "postgresql"
            ).label("deletion_blocker"),
            order_archived().label("archived"),
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
    now = datetime.now(timezone.utc)
    return {
        row[0].order_id: {
            **{k: v for k, v in row._mapping.items() if k != "OrderModel"},
            "managers": managers[row[0].order_id],
            "attention_reasons": active_pick_reasons(
                now, row[0], row.picked, row.dispatch_paused, thresholds
            ),
            "last_activity_at": latest_order_activity(row[0], row.related_at),
        }
        for row in rows
    }


def _mark_test_order(session: Session, order_id: UUID, marked: bool) -> str:
    was_marked = session.scalar(
        select(_is_test_order()).where(OrderModel.order_id == order_id)
    )
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


def _delete_test_order(session: Session, order: OrderModel) -> str:
    blocker = session.scalar(
        select(
            order_deletion_blocker(
                postgresql=session.get_bind().dialect.name == "postgresql"
            )
        ).where(OrderModel.order_id == order.order_id)
    )
    if blocker:
        return f"Удалить можно только тестовый черновик без связей. {blocker}."
    previous_status = order.status.value
    order.status = OrderStatus.DELETED
    order.dispatch_stopped = True
    order.updated_at = datetime.now(timezone.utc)
    session.add(
        AuditLogModel(
            entity_type="order",
            entity_id=order.order_id,
            action=AuditAction.DELETE,
            old_values={"status": previous_status},
            new_values={"status": OrderStatus.DELETED.value, "test": True},
        )
    )
    return "Тестовый заказ удалён."


def _record_worklist_flag(
    session: Session, order_id: UUID, entity: str, key: str, value: bool
) -> None:
    previous = session.scalar(_latest_worklist_event(order_id, entity))
    before = (
        previous.new_values.get(key, key == "visible")
        if previous
        else key == "visible"
    )
    if before == value:
        return
    changed_at = datetime.now(timezone.utc)
    if previous is not None:
        # Preserve event ordering when application clocks differ.
        last_change = previous.changed_at
        if last_change.tzinfo is None:
            last_change = last_change.replace(tzinfo=timezone.utc)
        changed_at = max(changed_at, last_change + timedelta(microseconds=1))
    session.add(
        AuditLogModel(
            entity_type=entity,
            entity_id=order_id,
            action=AuditAction.UPDATE,
            old_values={key: before},
            new_values={key: value},
            changed_at=changed_at,
        )
    )


def _set_order_visibility(
    session: Session, order_id: UUID, visible: bool
) -> str:
    if not visible and not session.scalar(
        select(_can_hide()).where(OrderModel.order_id == order_id)
    ):
        return "Заказ уже в работе или связан с оплатой. Скрытие недоступно."
    _record_worklist_flag(
        session, order_id, _VISIBILITY_ENTITY, "visible", visible
    )
    return "Заказ возвращён в список." if visible else "Заказ убран из списка."


def change_order_worklist(
    session: Session, order_id: UUID, operation: str
) -> str:
    if (
        operation == "delete-test"
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
    if operation == "delete-test":
        return _delete_test_order(session, order)
    if operation in {"hide", "restore"}:
        return _set_order_visibility(session, order_id, operation == "restore")
    if operation in {"archive-order", "restore-archived"}:
        archived = operation == "archive-order"
        _record_worklist_flag(
            session, order_id, _ARCHIVE_ENTITY, "archived", archived
        )
        return (
            "Заказ удалён из списка. Его можно вернуть из вкладки «Удалённые»."
            if archived
            else "Заказ возвращён из удалённых."
        )
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
