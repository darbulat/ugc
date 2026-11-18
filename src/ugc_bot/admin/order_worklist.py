"""Queries and single-order actions for the SQLAdmin orders list."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import (
    String,
    and_,
    case,
    cast,
    func,
    or_,
    select,
    text,
    true,
    union,
    update,
)
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql import ColumnElement

from ugc_bot.admin.complaints import OPEN_COMPLAINT_STATUSES
from ugc_bot.admin.order_progress import (
    financial_order_ids,
    load_order_progress,
)
from ugc_bot.admin.order_summary import (
    DelayThresholds,
    active_pick_reasons,
    latest_order_activity,
    manager_contact,
    order_activity_at,
    order_managers_query,
    picked_order_count,
)
from ugc_bot.domain.enums import (
    AuditAction,
    OrderStatus,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.checkout_models import CHECKOUTS, INBOX
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.dispatch_control import CONTROLS
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    BloggerRatingModel,
    ComplaintModel,
    InteractionModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    OutboxEventModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_intake_models import ACCOMPANIMENT_LEADS
from ugc_bot.infrastructure.db.order_review_models import OWNERS

ORDER_STATUS_LABELS = {
    OrderStatus.NEW: "Новый",
    OrderStatus.PENDING_MODERATION: "На модерации",
    OrderStatus.ACTIVE: "Активный",
    OrderStatus.CLOSED: "Закрытый",
}
ORDER_CLOSURE_REASON_LIMIT = 500
ORDER_CLOSURE_SAVED_MESSAGE = "Причина закрытия сохранена."
ORDER_CLOSED_MESSAGE = "Заказ закрыт."
_CLOSURE_REASON_LABELS = {
    "customer_cancelled_unpaid_order": "Заказчик отменил заявку до оплаты.",
    "owner_requested_close_orders_before_november_2026": (
        "По запросу владельца закрыли заявки, созданные до 01.11.2026."
    ),
}
_VISIBILITY_ENTITY = "order_worklist_visibility"
_TEST_ORDER_ENTITY = "order_test_marker"
_CLOSURE_REASON_ENTITY = "order_closure_reason"
_TEST_ACCOUNT_NAMES = (
    "булат",
    "эмилий",
    "камиль",
    "kamil_kahan",
    "usemycontent",
    "oneday_support",
)
_TEST_ACCOUNT_ALIASES = frozenset(
    variant
    for name in _TEST_ACCOUNT_NAMES
    for variant in (name, name.title(), name.upper())
)
TEST_REVIEW_GROUP = "check-test"
_ARCHIVE_ENTITY = "order_worklist_archive"
UNPAID_GROUP = "unpaid"
MANAGER_ASSIGNMENT_GROUPS = ("work", UNPAID_GROUP, "all", "test")
_MANAGER_ASSIGNMENT_ENTITY = "order_manager_assignment"


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


def _order_test_marker():
    return (
        _latest_worklist_event(OrderModel.order_id, _TEST_ORDER_ENTITY)
        .with_only_columns(AuditLogModel.new_values["test"].as_boolean())
        .correlate(OrderModel)
        .scalar_subquery()
    )


def _is_test_order():
    return _order_test_marker().is_(True)


def order_test_candidate():
    # Match whole account names to avoid flagging similar names and brands.
    account = UserModel.__table__.alias("test_candidate_account")
    profile = AdvertiserProfileModel.__table__.alias("test_candidate_profile")
    aliases = [
        func.lower(func.ltrim(func.trim(field), "@")).in_(_TEST_ACCOUNT_ALIASES)
        for field in (account.c.username, account.c.telegram, profile.c.brand)
    ]
    return _order_test_marker().is_(None) & (
        select(account.c.user_id)
        .select_from(
            account.outerjoin(profile, profile.c.user_id == account.c.user_id)
        )
        .where(account.c.user_id == OrderModel.advertiser_id, or_(*aliases))
        .correlate(OrderModel)
        .exists()
    )


def business_order_conditions():
    return (*worklist_conditions("all", ""), ~_is_test_order())


def order_deletion_blocker(*, postgresql: bool):
    """Return the first reason the guarded test deletion would refuse."""
    checks = [
        (~_is_test_order(), "Заказ не отмечен как служебный"),
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


def _has_order_payment():
    return (
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


def aging_unpaid_condition(now: datetime, hours: int):
    return (
        (OrderModel.status == OrderStatus.NEW)
        & (OrderModel.created_at <= now - timedelta(hours=hours))
        & ~_has_order_payment()
        & ~_is_test_order()
        & ~order_test_candidate()
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

    if group == TEST_REVIEW_GROUP:
        return [
            OrderModel.status != OrderStatus.DELETED,
            order_test_candidate(),
            *scope,
        ]

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


def _order_search_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _order_search_word(word: str):
    pattern = _order_search_pattern(word.replace("ё", "е").replace("Ё", "Е"))

    def matches(column):
        normalized = func.replace(func.replace(column, "ё", "е"), "Ё", "Е")
        return normalized.ilike(pattern, escape="\\")

    handle = word.removeprefix("@") or word
    telegram = UserModel.telegram.ilike(
        _order_search_pattern(handle), escape="\\"
    )

    return or_(
        *(
            matches(column)
            for column in (
                OrderModel.offer_text,
                OrderModel.barter_description,
                OrderModel.product_link,
                OrderModel.geography,
                OrderModel.brief_link,
            )
        ),
        cast(OrderModel.order_id, String).ilike(pattern, escape="\\"),
        select(UserModel.user_id)
        .where(
            UserModel.user_id == OrderModel.advertiser_id,
            or_(matches(UserModel.username), telegram),
        )
        .exists(),
        select(AdvertiserProfileModel.user_id)
        .where(
            AdvertiserProfileModel.user_id == OrderModel.advertiser_id,
            matches(AdvertiserProfileModel.brand),
        )
        .exists(),
    )


def search_orders(term: str):
    term = term.strip()
    # Bound the number of SQL predicates. For longer pasted text, keep the
    # remaining text together as a phrase.
    terms = dict.fromkeys(term.split(maxsplit=15))
    condition = and_(true(), *(_order_search_word(word) for word in terms))
    try:
        order_id = UUID(term)
    except ValueError:
        return condition
    return or_(OrderModel.order_id == order_id, condition)


def order_closure_reason():
    """Find the latest reason or status transition for the current closure."""
    status = AuditLogModel.new_values["status"].as_string()
    previous = AuditLogModel.old_values["status"].as_string()
    supplemental = AuditLogModel.entity_type == _CLOSURE_REASON_ENTITY
    return (
        select(
            case(
                (
                    or_(supplemental, status == OrderStatus.CLOSED.value),
                    AuditLogModel.new_values["reason"].as_string(),
                )
            )
        )
        .where(
            AuditLogModel.entity_id == OrderModel.order_id,
            AuditLogModel.action == AuditAction.UPDATE,
            or_(
                supplemental,
                and_(
                    AuditLogModel.entity_type == "order",
                    status.is_not(None),
                    status.is_distinct_from(previous),
                ),
            ),
            or_(
                OrderModel.completed_at.is_(None),
                AuditLogModel.changed_at >= OrderModel.completed_at,
            ),
        )
        .order_by(AuditLogModel.changed_at.desc(), AuditLogModel.id.desc())
        .limit(1)
        .correlate(OrderModel)
        .scalar_subquery()
    )


def format_order_closure_reason(value: str | None) -> str:
    reason = value.strip() if isinstance(value, str) else ""
    return _CLOSURE_REASON_LABELS.get(reason, reason)


def worklist_closure_reasons(
    session: Session, order_ids: list[UUID]
) -> dict[UUID, str]:
    if not order_ids:
        return {}
    rows = session.execute(
        select(OrderModel.order_id, order_closure_reason()).where(
            OrderModel.order_id.in_(order_ids),
            OrderModel.status == OrderStatus.CLOSED,
        )
    )
    return {
        order_id: reason
        for order_id, value in rows
        if (reason := format_order_closure_reason(value))
    }


def order_requires_closure_reason(*, postgresql: bool) -> ColumnElement[bool]:
    previously_active = (
        select(AuditLogModel.id)
        .where(
            AuditLogModel.entity_id == OrderModel.order_id,
            AuditLogModel.entity_type == "order",
            or_(
                AuditLogModel.old_values["status"].as_string()
                == OrderStatus.ACTIVE.value,
                AuditLogModel.new_values["status"].as_string()
                == OrderStatus.ACTIVE.value,
            ),
        )
        .correlate(OrderModel)
        .exists()
    )
    launched = [
        OrderModel.status == OrderStatus.ACTIVE,
        OrderModel.complimentary.is_(True),
        _order_has(OfferDispatchModel.__table__),
        _order_has(CONTROLS),
        previously_active,
    ]
    if postgresql:
        launched.append(
            select(OutboxEventModel.event_id)
            .where(
                OutboxEventModel.aggregate_id
                == cast(OrderModel.order_id, String),
                OutboxEventModel.event_type == "order.activated",
            )
            .correlate(OrderModel)
            .exists()
        )
        launched.append(
            select(INVITES.c.order_id)
            .where(
                INVITES.c.order_id == OrderModel.order_id,
                INVITES.c.reported_at.is_not(None),
            )
            .correlate(OrderModel)
            .exists()
        )
    captured_position = (
        select(OrderItemModel.order_id)
        .where(
            OrderItemModel.order_id == OrderModel.order_id,
            OrderItemModel.captured_at.is_not(None),
        )
        .correlate(OrderModel)
        .exists()
    )
    return or_(
        *launched,
        _has_order_payment(),
        captured_position,
        picked_order_count() > 0,
    )


def order_missing_required_reason(*, postgresql: bool) -> ColumnElement[bool]:
    return func.nullif(func.trim(order_closure_reason()), "").is_(
        None
    ) & order_requires_closure_reason(postgresql=postgresql)


def worklist_row_details(
    session: Session, order_ids: list[UUID], thresholds: DelayThresholds
):
    if not order_ids:
        return {}
    position_managers = set(
        session.execute(_paid_position_managers(order_ids)).tuples()
    )
    managers = defaultdict(list)
    replaceable = defaultdict(list)
    for manager in session.execute(order_managers_query(order_ids)):
        contact = manager_contact(manager)
        managers[manager.order_id].append(contact)
        if (manager.order_id, manager.user_id) not in position_managers:
            replaceable[manager.order_id].append(contact)
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
            order_test_candidate().label("test_candidate"),
            order_requires_closure_reason(
                postgresql=session.get_bind().dialect.name == "postgresql"
            ).label("requires_closure_reason"),
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
    ).all()
    progress = load_order_progress(
        session, financial_order_ids(row[0] for row in rows)
    )
    now = datetime.now(timezone.utc)
    return {
        row[0].order_id: {
            **{k: v for k, v in row._mapping.items() if k != "OrderModel"},
            "managers": managers[row[0].order_id],
            "transferred_count": (
                progress[row[0].order_id].transferred_count
                if row[0].order_id in progress
                else None
            ),
            "replaceable_managers": replaceable[row[0].order_id],
            "attention_reasons": active_pick_reasons(
                now, row[0], row.picked, row.dispatch_paused, thresholds
            ),
            "last_activity_at": latest_order_activity(row[0], row.related_at),
        }
        for row in rows
    }


def _mark_test_order(
    session: Session,
    order_id: UUID,
    marked: bool,
    *,
    confirming_real: bool = False,
) -> str:
    was_marked = session.scalar(
        select(_order_test_marker()).where(OrderModel.order_id == order_id)
    )
    if (was_marked if confirming_real else bool(was_marked)) != marked:
        session.add(
            AuditLogModel(
                entity_type=_TEST_ORDER_ENTITY,
                entity_id=order_id,
                action=AuditAction.UPDATE,
                old_values={"test": bool(was_marked)},
                new_values={"test": marked},
            )
        )
    return (
        "Заказ отмечен как служебный." if marked else "Служебная отметка снята."
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
        return f"Удалить можно только служебный черновик без связей. {blocker}."
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
    return "Служебный заказ удалён."


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


def worklist_manager_suggestions(session: Session) -> list[str]:
    """Suggest existing managers without including other users."""
    telegram = func.lower(UserModel.telegram)
    has_assignment = (
        select(1).where(ManagerOrderModel.user_id == UserModel.user_id).exists()
    )
    eligible = (
        or_(
            has_assignment,
            select(1)
            .where(
                APPLICATIONS.c.user_id == UserModel.user_id,
                APPLICATIONS.c.state == "approved",
            )
            .exists(),
        )
        if session.get_bind().dialect.name == "postgresql"
        and session.scalar(select(func.to_regclass(APPLICATIONS.name)))
        else has_assignment
    )
    return list(
        session.scalars(
            select(telegram)
            .where(
                eligible,
                UserModel.telegram.is_not(None),
                UserModel.telegram != "",
                UserModel.status == UserStatus.ACTIVE,
            )
            .distinct()
            .order_by(telegram)
        )
    )


def _paid_position_managers(order_ids: list[UUID]):
    return union(
        select(OrderItemModel.order_id, ItemAssignmentModel.manager_id)
        .join(
            ItemAssignmentModel,
            ItemAssignmentModel.paid_item_id == OrderItemModel.paid_item_id,
        )
        .where(
            OrderItemModel.order_id.in_(order_ids),
            ItemAssignmentModel.valid_to.is_(None),
            ItemAssignmentModel.manager_id.is_not(None),
        ),
        select(OrderItemModel.order_id, OWNERS.c.manager_id)
        .join(OWNERS, OWNERS.c.paid_item_id == OrderItemModel.paid_item_id)
        .where(OrderItemModel.order_id.in_(order_ids)),
    )


@dataclass(frozen=True, slots=True)
class ManagerChange:
    message: str
    order_title: str = ""
    telegram_id: str | None = None
    notify: bool = False


def _transfer_manager(
    session: Session,
    order: OrderModel,
    previous: UUID,
    target: UUID,
    now: datetime,
) -> None:
    membership = session.get(ManagerOrderModel, (previous, order.order_id))
    if membership is not None:
        session.delete(membership)
    if order.financial_version is None or order.complimentary:
        session.execute(
            update(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order.order_id,
                OfferDispatchModel.manager_id == previous,
            )
            .values(manager_id=target, updated_at=now)
        )


def assign_worklist_manager(
    session: Session,
    order_id: UUID,
    telegram: str,
    *,
    previous_manager: UUID | None = None,
) -> ManagerChange:
    """Set one manager under the order lock shared by admin edits."""
    candidates = session.scalars(
        select(UserModel)
        .where(func.lower(UserModel.telegram) == telegram)
        .limit(2)
        .with_for_update(read=True)
    ).all()
    if not candidates:
        return ManagerChange(
            "Пользователь с таким Telegram-ником не найден в боте."
        )
    if len(candidates) > 1:
        return ManagerChange(
            "По этому Telegram-нику найдено несколько аккаунтов."
        )
    manager = candidates[0]
    if manager.status != UserStatus.ACTIVE:
        return ManagerChange("Для назначения нужен активный аккаунт в боте.")

    order = session.get(OrderModel, order_id, with_for_update=True)
    eligible_order = select(_is_test_order()).where(
        OrderModel.order_id == order_id,
        OrderModel.status != OrderStatus.CLOSED,
        *worklist_conditions("all", "", admin_list=True),
    )
    is_test = session.scalar(eligible_order)
    if order is None or is_test is None:
        return ManagerChange("Заказ недоступен для назначения менеджера.")
    if manager.user_id == order.advertiser_id:
        return ManagerChange(
            "Выберите менеджера, который не является заказчиком."
        )

    current = {
        row.user_id: row.telegram
        for row in session.execute(order_managers_query([order_id]))
    }
    if previous_manager is not None:
        return _replace_worklist_manager(
            session,
            order,
            manager,
            telegram,
            previous_manager,
            current,
            is_test=is_test,
        )
    if current:
        return ManagerChange("У заказа уже есть менеджер. Обновили список.")

    return _save_manager_change(
        session, order, manager, telegram, is_test=is_test
    )


def _replace_worklist_manager(
    session: Session,
    order: OrderModel,
    manager: UserModel,
    telegram: str,
    previous: UUID,
    current: dict[UUID, str | None],
    *,
    is_test: bool,
) -> ManagerChange:
    if previous not in current:
        return ManagerChange(
            "Менеджер уже изменился. Проверьте назначение в списке."
        )
    if previous == manager.user_id:
        return ManagerChange("Этот менеджер уже назначен на заказ.")
    if (order.order_id, previous) in session.execute(
        _paid_position_managers([order.order_id])
    ).tuples():
        return ManagerChange(
            "У менеджера есть оплаченные позиции. Быстрая замена недоступна."
        )

    now = datetime.now(timezone.utc)
    _transfer_manager(session, order, previous, manager.user_id, now)
    return _save_manager_change(
        session,
        order,
        manager,
        telegram,
        is_test=is_test,
        previous=(previous, current[previous]),
        was_on_order=manager.user_id in current,
    )


def _save_manager_change(
    session: Session,
    order: OrderModel,
    manager: UserModel,
    telegram: str,
    *,
    is_test: bool,
    previous: tuple[UUID, str | None] | None = None,
    was_on_order: bool = False,
) -> ManagerChange:
    now = datetime.now(timezone.utc)
    assignment = session.get(
        ManagerOrderModel, (manager.user_id, order.order_id)
    )
    if assignment is None:
        session.add(
            ManagerOrderModel(
                user_id=manager.user_id,
                order_id=order.order_id,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        assignment.updated_at = now
    old_values: dict[str, str | None] = {"manager_id": None}
    new_values = {"manager_id": str(manager.user_id)}
    message = f"Менеджер @{telegram} назначен."
    if previous is not None:
        old_values = {"manager_id": str(previous[0]), "telegram": previous[1]}
        new_values["telegram"] = telegram
        message = f"Менеджер заменён на @{telegram}."
    session.add(
        AuditLogModel(
            entity_type=_MANAGER_ASSIGNMENT_ENTITY,
            entity_id=order.order_id,
            action=AuditAction.UPDATE,
            old_values=old_values,
            new_values=new_values,
            changed_at=now,
        )
    )
    return ManagerChange(
        message,
        order_title=" ".join((order.offer_text or "").split())[:120],
        telegram_id=manager.telegram_id,
        notify=not is_test and not was_on_order,
    )


def _validate_closure_reason(value: object, *, required: bool) -> str:
    reason = value.strip() if isinstance(value, str) else ""
    if required and not reason:
        raise ValueError("Укажите причину закрытия.")
    if len(reason) > ORDER_CLOSURE_REASON_LIMIT:
        raise ValueError(
            f"Причина закрытия должна быть не длиннее "
            f"{ORDER_CLOSURE_REASON_LIMIT} символов."
        )
    return reason


def _closure_reason_required_for(session: Session, order_id: UUID):
    return session.scalar(
        select(
            order_requires_closure_reason(
                postgresql=session.get_bind().dialect.name == "postgresql"
            )
        ).where(OrderModel.order_id == order_id)
    )


def record_closed_order_reason(
    session: Session, order_id: UUID, value: object
) -> str:
    order = session.get(OrderModel, order_id, with_for_update=True)
    if order is None or order.status != OrderStatus.CLOSED:
        return "Причину можно сохранить только для закрытого заказа."
    if not _closure_reason_required_for(session, order_id):
        return "К заказу не привязаны оплата, запуск или подбор."
    try:
        reason = _validate_closure_reason(value, required=True)
    except ValueError as error:
        return str(error)
    old_reason = session.scalar(
        select(order_closure_reason()).where(OrderModel.order_id == order_id)
    )
    if reason != format_order_closure_reason(old_reason):
        session.add(
            AuditLogModel(
                entity_type=_CLOSURE_REASON_ENTITY,
                entity_id=order_id,
                action=AuditAction.UPDATE,
                old_values={"reason": old_reason},
                new_values={"reason": reason},
            )
        )
    return ORDER_CLOSURE_SAVED_MESSAGE


def close_order_with_reason(
    session: Session, order: OrderModel, value: object
) -> None:
    reason = _validate_closure_reason(value, required=False)
    if not reason and _closure_reason_required_for(session, order.order_id):
        raise ValueError("Укажите причину закрытия.")

    now = datetime.now(timezone.utc)
    previous_status = order.status.value
    order.status = OrderStatus.CLOSED
    order.dispatch_stopped = True
    order.completed_at = now
    order.updated_at = now
    new_values = {"status": OrderStatus.CLOSED.value}
    if reason:
        new_values["reason"] = reason
    session.add(
        AuditLogModel(
            entity_type="order",
            entity_id=order.order_id,
            action=AuditAction.UPDATE,
            old_values={"status": previous_status},
            new_values=new_values,
            changed_at=now,
        )
    )


def _review_test_order(session: Session, order_id: UUID, operation: str) -> str:
    if operation == "confirm-real":
        if session.scalar(
            select(order_test_candidate()).where(
                OrderModel.order_id == order_id
            )
        ):
            _mark_test_order(session, order_id, False, confirming_real=True)
            return "Заказ отмечен как реальный."
        return "Заказ уже проверен или отсутствует в списке на проверку."
    return _mark_test_order(session, order_id, operation == "mark-test")


def change_order_worklist(
    session: Session,
    order_id: UUID,
    operation: str,
    *,
    closure_reason: object = None,
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
    if operation in {"mark-test", "unmark-test", "confirm-real"}:
        return _review_test_order(session, order_id, operation)
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

    try:
        close_order_with_reason(session, order, closure_reason)
    except ValueError as error:
        return str(error)
    return ORDER_CLOSED_MESSAGE
