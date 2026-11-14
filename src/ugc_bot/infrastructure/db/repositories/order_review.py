"""Read paid-position evidence for the staff queue and deadline alerts."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, case, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from ugc_bot.application.services.financial_reconciliation_service import (
    BUCKETS,
)
from ugc_bot.domain.enums import AuditAction, OrderStatus
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel
from ugc_bot.infrastructure.db.correction_models import TABLE_MAP as CORRECTIONS
from ugc_bot.infrastructure.db.customer_workflow_models import REQUESTS
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    FinancialMovementModel,
    FinancialObligationModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_review_models import ALERTS, OWNERS
from ugc_bot.infrastructure.db.order_summary_models import REPORTS
from ugc_bot.infrastructure.db.paid_selection_models import INTERESTS, JOBS
from ugc_bot.infrastructure.db.replacement_models import TABLES as REPLACEMENTS
from ugc_bot.infrastructure.db.repositories.order_summary import report_state
from ugc_bot.infrastructure.db.selection_delivery_models import ACCEPTED
from ugc_bot.infrastructure.db.selection_maturity_models import (
    TABLES as MATURITY,
)


def _latest_flag(entity, key):
    return (
        select(AuditLogModel.new_values[key].as_boolean())
        .where(
            AuditLogModel.entity_type == entity,
            AuditLogModel.entity_id == OrderModel.order_id,
        )
        .order_by(AuditLogModel.changed_at.desc(), AuditLogModel.id.desc())
        .limit(1)
        .correlate(OrderModel)
        .scalar_subquery()
        .is_not(True)
    )


def _active_orders():
    return (
        OrderModel.financial_version.is_not(None),
        OrderModel.complimentary.is_(False),
        OrderModel.status == OrderStatus.ACTIVE,
        _latest_flag("order_test_marker", "test"),
        _latest_flag("order_worklist_archive", "archived"),
    )


def _order_team(order_id, client_id):
    return (
        select(UserModel.user_id, UserModel.username, UserModel.telegram)
        .join(ManagerOrderModel, ManagerOrderModel.user_id == UserModel.user_id)
        .where(
            ManagerOrderModel.order_id == order_id,
            UserModel.user_id != client_id,
            UserModel.status == "active",
        )
    )


def _positions():
    item, assignment, order = OrderItemModel, ItemAssignmentModel, OrderModel
    managers = _order_team(order.order_id, order.advertiser_id).correlate(order)
    manager_id = func.coalesce(OWNERS.c.manager_id, assignment.manager_id)
    responsible = case(
        (
            manager_id.in_(managers.with_only_columns(UserModel.user_id)),
            manager_id,
        ),
        (
            managers.with_only_columns(
                func.count(UserModel.user_id)
            ).scalar_subquery()
            == 1,
            managers.with_only_columns(UserModel.user_id)
            .limit(1)
            .scalar_subquery(),
        ),
    )
    replacement = REPLACEMENTS["allocations"]
    contact = REPLACEMENTS["contacts"]
    disclosed = (
        select(func.min(contact.c.recorded_at))
        .where(
            contact.c.replacement_id == replacement.c.replacement_id,
            contact.c.actor_id == order.advertiser_id,
        )
        .correlate(replacement, order)
        .scalar_subquery()
    )
    refund = CORRECTIONS["components"]
    full_refund = (
        select(func.coalesce(func.sum(refund.c.refund_minor), 0))
        .where(
            refund.c.paid_item_id == item.paid_item_id,
            refund.c.component == "selection",
        )
        .correlate(item)
        .scalar_subquery()
        >= item.selection_minor
    )
    original_contact = (
        select(ACCEPTED.c.accepted_at)
        .where(ACCEPTED.c.assignment_id == assignment.assignment_id)
        .correlate(assignment)
        .scalar_subquery()
    )
    delivery = (
        select(JOBS.c.state)
        .join(INTERESTS, INTERESTS.c.interest_id == JOBS.c.interest_id)
        .where(INTERESTS.c.assignment_id == assignment.assignment_id)
        .correlate(assignment)
        .scalar_subquery()
    )
    creator = aliased(UserModel)
    work = CollaborationModel
    return (
        select(
            order.order_id,
            order.advertiser_id,
            order.offer_text,
            item.paid_item_id,
            item.ordinal,
            item.selection_due_at.label("deadline"),
            responsible.label("manager_id"),
            OWNERS.c.manager_id.label("owner_override"),
            assignment.creator_id,
            func.coalesce(creator.username, creator.telegram).label("creator"),
            func.coalesce(original_contact, disclosed).label("contact_at"),
            delivery.label("delivery_state"),
            work.state.label("work_state"),
            work.due_at.label("work_due_at"),
            report_state().label("report_state"),
            REPORTS.c.review_reason,
            REPORTS.c.answer_due_at,
        )
        .select_from(item)
        .join(order, order.order_id == item.order_id)
        .outerjoin(OWNERS, OWNERS.c.paid_item_id == item.paid_item_id)
        .outerjoin(
            assignment,
            and_(
                assignment.paid_item_id == item.paid_item_id,
                assignment.valid_to.is_(None),
            ),
        )
        .outerjoin(creator, creator.user_id == assignment.creator_id)
        .outerjoin(work, work.assignment_id == assignment.assignment_id)
        .outerjoin(
            replacement, replacement.c.assignment_id == assignment.assignment_id
        )
        .outerjoin(REPORTS, REPORTS.c.assignment_id == assignment.assignment_id)
        .outerjoin(
            REQUESTS, REQUESTS.c.request_id == REPORTS.c.support_request_id
        )
        .where(
            *_active_orders(),
            item.captured_at.is_not(None),
            item.selection_state.in_(("paid", "delivered")),
            ~full_refund,
        )
        .subquery()
    )


def _due_positions(at, start_at):
    positions = _positions()
    return (
        select(
            positions,
            case(
                (positions.c.deadline <= at, "overdue"), else_="upcoming"
            ).label("stage"),
        )
        .where(
            positions.c.deadline >= start_at,
            positions.c.deadline <= at + timedelta(hours=24),
            positions.c.contact_at.is_(None),
        )
        .cte("order_review_due")
    )


def _duty_admin(duty_id):
    return select(UserModel.user_id).where(
        UserModel.user_id == duty_id,
        UserModel.admin.is_(True),
        UserModel.status == "active",
        UserModel.telegram_id.regexp_match(r"^[1-9][0-9]*$"),
    )


def _recipient_scope(due, duty_id):
    return (
        select(
            due.c.order_id,
            due.c.advertiser_id,
            due.c.deadline,
            due.c.stage,
            due.c.manager_id.label("recipient_id"),
        )
        .where(due.c.manager_id.is_not(None))
        .union(
            select(
                due.c.order_id,
                due.c.advertiser_id,
                due.c.deadline,
                due.c.stage,
                _duty_admin(duty_id).scalar_subquery(),
            )
        )
        .subquery()
    )


def schedule_alerts(db, at, start_at, duty_id, limit=50):
    scope = _recipient_scope(_due_positions(at, start_at), duty_id)
    pending = (
        db.execute(
            select(
                scope.c.order_id,
                scope.c.deadline,
                scope.c.stage,
                scope.c.recipient_id,
            )
            .join(UserModel, UserModel.user_id == scope.c.recipient_id)
            .where(
                UserModel.status == "active",
                UserModel.telegram_id.regexp_match(r"^[1-9][0-9]*$"),
                scope.c.recipient_id != scope.c.advertiser_id,
                scope.c.recipient_id.is_not(None),
                ~exists().where(
                    ALERTS.c.order_id == scope.c.order_id,
                    ALERTS.c.deadline == scope.c.deadline,
                    ALERTS.c.stage == scope.c.stage,
                    ALERTS.c.recipient_id == scope.c.recipient_id,
                    ALERTS.c.state != "obsolete",
                ),
            )
            .order_by(scope.c.deadline, scope.c.order_id, scope.c.recipient_id)
            .limit(limit)
        )
        .mappings()
        .all()
    )
    if pending:
        db.execute(
            insert(ALERTS)
            .values(
                [
                    dict(row, id=uuid4(), state="ready", ready_at=at)
                    for row in pending
                ]
            )
            .on_conflict_do_update(
                index_elements=[
                    "order_id",
                    "deadline",
                    "stage",
                    "recipient_id",
                ],
                set_={"state": "ready", "ready_at": at},
                where=ALERTS.c.state == "obsolete",
            )
        )


def claim_alert(db, at, start_at, duty_id):
    db.execute(
        update(ALERTS)
        .where(
            ALERTS.c.state == "sending",
            ALERTS.c.started_at <= at - timedelta(minutes=5),
        )
        .values(state="unknown")
    )
    job = (
        db.execute(
            select(ALERTS)
            .where(ALERTS.c.state == "ready", ALERTS.c.ready_at <= at)
            .order_by(ALERTS.c.ready_at, ALERTS.c.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        .mappings()
        .one_or_none()
    )
    if job is None:
        return None
    user = db.get(UserModel, job["recipient_id"])
    positions = _due_positions(at, start_at)
    is_duty = job["recipient_id"] == duty_id and bool(user and user.admin)
    ordinals = db.scalars(
        select(positions.c.ordinal)
        .where(
            positions.c.order_id == job["order_id"],
            positions.c.deadline == job["deadline"],
            positions.c.stage == job["stage"],
            positions.c.advertiser_id != job["recipient_id"],
            or_(
                positions.c.manager_id == job["recipient_id"],
                is_duty,
            ),
        )
        .order_by(positions.c.ordinal)
    ).all()
    address = user.telegram_id if user and user.status == "active" else None
    client_address = db.scalar(
        select(UserModel.telegram_id)
        .join(OrderModel, OrderModel.advertiser_id == UserModel.user_id)
        .where(OrderModel.order_id == job["order_id"])
    )
    if (
        not ordinals
        or not address
        or address == client_address
        or not address.isascii()
        or not address.isdecimal()
        or address.startswith("0")
    ):
        db.execute(
            update(ALERTS)
            .where(ALERTS.c.id == job["id"])
            .values(state="obsolete")
        )
        return {}
    db.execute(
        update(ALERTS)
        .where(ALERTS.c.id == job["id"])
        .values(state="sending", started_at=at)
    )
    return dict(
        job,
        ordinals=ordinals,
        address=address,
        started_at=at,
        duty=is_duty,
    )


def finish_alert(db, job, state, reference, retry_at):
    values = dict(state=state, provider_reference=reference)
    if retry_at is not None:
        values.update(ready_at=retry_at, started_at=None)
    db.execute(
        update(ALERTS)
        .where(
            ALERTS.c.id == job["id"],
            ALERTS.c.state == "sending",
            ALERTS.c.started_at == job["started_at"],
        )
        .values(**values)
    )


def _attention(p, at):
    return or_(
        and_(p.deadline <= at + timedelta(hours=24), p.contact_at.is_(None)),
        p.report_state.in_(("queued", "waiting", "review")),
        p.work_state == "disputed",
        and_(
            p.work_due_at <= at,
            p.work_state.in_(("assigned", "in_progress", "success_claimed")),
        ),
        p.delivery_state.in_(("failed", "unknown")),
    )


def list_positions(
    db, at, order_id, manager_id, unassigned, offset=0, limit=50
):
    p = _positions().c
    conditions = [_attention(p, at)]
    if order_id is not None:
        conditions.append(p.order_id == order_id)
    if unassigned:
        conditions.append(p.manager_id.is_(None))
    elif manager_id is not None:
        conditions.append(p.manager_id == manager_id)
    query = (
        select(p).where(*conditions).order_by(p.deadline, p.order_id, p.ordinal)
    )
    return db.execute(query.offset(offset).limit(limit)).mappings().all()


def set_position_manager(db, order_id, item_id, manager_id, expected, at):
    # Serialize changes to the queue owner and compare the submitted assignment.
    order = db.scalar(
        select(OrderModel)
        .where(OrderModel.order_id == order_id, *_active_orders())
        .with_for_update()
    )
    if order is None:
        return "Позиция недоступна."
    positions = _positions()
    if not db.scalar(
        select(positions.c.paid_item_id).where(
            positions.c.paid_item_id == item_id,
            positions.c.order_id == order_id,
            _attention(positions.c, at),
        )
    ):
        return "Позиция недоступна."
    current = db.scalar(
        select(OWNERS.c.manager_id).where(OWNERS.c.paid_item_id == item_id)
    )
    if current != expected:
        return "Ответственный уже изменился. Проверьте назначение."
    if manager_id == current:
        return "Ответственный сохранён."
    if manager_id is None:
        db.execute(delete(OWNERS).where(OWNERS.c.paid_item_id == item_id))
    else:
        if (
            db.scalar(
                _order_team(order_id, order.advertiser_id).where(
                    UserModel.user_id == manager_id
                )
            )
            is None
        ):
            return "Выберите активного менеджера этого заказа."
        upsert = insert(OWNERS).values(
            paid_item_id=item_id, manager_id=manager_id, assigned_at=at
        )
        db.execute(
            upsert.on_conflict_do_update(
                index_elements=[OWNERS.c.paid_item_id],
                set_={
                    "manager_id": upsert.excluded.manager_id,
                    "assigned_at": upsert.excluded.assigned_at,
                },
            )
        )
    db.add(
        AuditLogModel(
            entity_type="order_review_owner",
            entity_id=item_id,
            action=AuditAction.UPDATE,
            old_values={"manager_id": str(current) if current else None},
            new_values={
                "manager_id": str(manager_id) if manager_id else None,
                "order_id": str(order_id),
            },
        )
    )
    return "Ответственный сохранён."


def review_details(db, order_id, client_id):
    managers = (
        db.execute(
            _order_team(order_id, client_id).order_by(
                UserModel.username, UserModel.user_id
            )
        )
        .mappings()
        .all()
    )
    allocations = REPLACEMENTS["allocations"]
    item = OrderItemModel
    used = db.scalar(
        select(func.count())
        .select_from(allocations)
        .join(item, item.paid_item_id == allocations.c.paid_item_id)
        .where(item.order_id == order_id)
    )
    total = db.scalar(
        select(func.count())
        .select_from(item)
        .where(item.order_id == order_id, item.captured_at.is_not(None))
    )
    candidates = db.scalar(
        select(func.count())
        .select_from(INTERESTS)
        .where(
            INTERESTS.c.order_id == order_id,
            INTERESTS.c.accepted.is_(False),
            ~exists().where(
                allocations.c.candidate_interest_id == INTERESTS.c.interest_id
            ),
            ~exists().where(
                ItemAssignmentModel.creator_id == INTERESTS.c.creator_id,
                ItemAssignmentModel.paid_item_id == item.paid_item_id,
                item.order_id == order_id,
            ),
        )
    )
    return managers, used, total // 5, candidates


def referral_entries(db, item_ids):
    obligation, movement = FinancialObligationModel, FinancialMovementModel
    schedule = MATURITY["schedules"]
    return (
        db.execute(
            select(
                obligation.paid_item_id,
                obligation.id,
                obligation.kind,
                obligation.amount_minor,
                obligation.currency,
                UserModel.username.label("recipient"),
                func.coalesce(
                    obligation.available_at, schedule.c.release_at
                ).label("available_at"),
                *(
                    (
                        func.sum(
                            case(
                                (
                                    movement.bucket_to == bucket,
                                    movement.amount_minor,
                                ),
                                else_=0,
                            )
                        )
                        - func.sum(
                            case(
                                (
                                    movement.bucket_from == bucket,
                                    movement.amount_minor,
                                ),
                                else_=0,
                            )
                        )
                    ).label(bucket)
                    for bucket in BUCKETS
                ),
                func.max(
                    case((movement.bucket_to == "paid", movement.effective_at))
                ).label("paid_at"),
            )
            .select_from(obligation)
            .join(UserModel, UserModel.user_id == obligation.recipient_id)
            .outerjoin(movement, movement.obligation_id == obligation.id)
            .outerjoin(
                schedule,
                and_(
                    schedule.c.paid_item_id == obligation.paid_item_id,
                    obligation.kind == "client_referral",
                ),
            )
            .where(
                obligation.paid_item_id.in_(item_ids),
                obligation.kind.in_(("client_referral", "creator_referral")),
            )
            .group_by(obligation.id, UserModel.username, schedule.c.release_at)
            .order_by(obligation.paid_item_id, obligation.kind, obligation.id)
        )
        .mappings()
        .all()
    )
