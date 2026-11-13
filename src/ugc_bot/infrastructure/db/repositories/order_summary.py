"""Storage for Telegram summaries and the evidence for replacement deadlines."""

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import and_, case, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel
from ugc_bot.infrastructure.db.customer_workflow_models import REQUESTS
from ugc_bot.infrastructure.db.models import (
    ItemAssignmentModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_summary_models import CARDS, JOBS, REPORTS
from ugc_bot.infrastructure.db.replacement_models import TABLES as REPLACEMENTS
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.selection_delivery_models import ACCEPTED
from ugc_bot.infrastructure.db.selection_maturity_models import (
    TABLES as MATURITY,
)


def summary_job_id(order_id, kind):
    return uuid5(NAMESPACE_URL, f"ugc:telegram-summary:{kind}:{order_id}")


def funded_order():
    return (
        OrderModel.financial_version.is_not(None),
        OrderModel.complimentary.is_(False),
        OrderModel.status.in_((OrderStatus.ACTIVE, OrderStatus.CLOSED)),
        exists().where(
            OrderItemModel.order_id == OrderModel.order_id,
            OrderItemModel.captured_at.is_not(None),
        ),
    )


def report_state():
    return case(
        (
            (REPORTS.c.state == "review") & (REQUESTS.c.state == "resolved"),
            "reviewed",
        ),
        else_=REPORTS.c.state,
    )


class SqlOrderSummary:
    async def card(self, order_id, client_id, at, *, session, lock=False):
        db = _session(session)
        order = await db.scalar(
            select(OrderModel).where(
                OrderModel.order_id == order_id,
                OrderModel.advertiser_id == client_id,
                *funded_order(),
            )
        )
        if order is None:
            raise PermissionError("summary_order_unavailable")
        if lock:
            await db.execute(
                insert(CARDS)
                .values(
                    order_id=order_id,
                    client_id=client_id,
                    draft={},
                    updated_at=at,
                )
                .on_conflict_do_nothing(index_elements=[CARDS.c.order_id])
            )
        query = select(CARDS).where(CARDS.c.order_id == order_id)
        if lock:
            query = query.with_for_update()
        card = (await db.execute(query)).mappings().one_or_none()
        if card is not None and card["client_id"] != client_id:
            raise PermissionError("summary_order_unavailable")
        return order, dict(card) if card is not None else None

    async def positions(self, order_id, *, session):
        assignment, item, work, creator = (
            ItemAssignmentModel,
            OrderItemModel,
            CollaborationModel,
            UserModel,
        )
        contacts = REPLACEMENTS["contacts"]
        allocations = REPLACEMENTS["allocations"]
        original_contact = (
            select(ACCEPTED.c.accepted_at)
            .where(
                ACCEPTED.c.paid_item_id == item.paid_item_id,
                ACCEPTED.c.assignment_id == assignment.assignment_id,
            )
            .correlate(item, assignment)
            .scalar_subquery()
        )
        replacement_contact = (
            select(func.min(contacts.c.recorded_at))
            .join(OrderModel, OrderModel.order_id == item.order_id)
            .where(
                contacts.c.replacement_id == allocations.c.replacement_id,
                contacts.c.actor_id == OrderModel.advertiser_id,
            )
            .correlate(item, allocations)
            .scalar_subquery()
        )
        delivered_at = func.coalesce(original_contact, replacement_contact)
        return (
            (
                await _session(session).execute(
                    select(
                        item.paid_item_id,
                        item.ordinal,
                        item.selection_state,
                        item.selection_due_at,
                        item.accompaniment_minor,
                        assignment.assignment_id,
                        assignment.creator_id,
                        assignment.version.label("assignment_version"),
                        creator.username,
                        work.state.label("work_state"),
                        work.version.label("work_version"),
                        work.due_at,
                        work.record_payload,
                        REPORTS.c.report_id,
                        report_state().label("report_state"),
                        REPORTS.c.answer_due_at,
                        REPLACEMENTS["allocations"].c.replacement_id,
                        delivered_at.label("contact_at"),
                        delivered_at.is_not(None).label("contact_delivered"),
                    )
                    .select_from(item)
                    .outerjoin(
                        assignment,
                        and_(
                            assignment.paid_item_id == item.paid_item_id,
                            assignment.valid_to.is_(None),
                        ),
                    )
                    .outerjoin(
                        creator, creator.user_id == assignment.creator_id
                    )
                    .outerjoin(
                        work, work.assignment_id == assignment.assignment_id
                    )
                    .outerjoin(
                        REPORTS,
                        REPORTS.c.assignment_id == assignment.assignment_id,
                    )
                    .outerjoin(
                        REQUESTS,
                        REQUESTS.c.request_id == REPORTS.c.support_request_id,
                    )
                    .outerjoin(
                        REPLACEMENTS["allocations"],
                        REPLACEMENTS["allocations"].c.assignment_id
                        == assignment.assignment_id,
                    )
                    .where(
                        item.order_id == order_id, item.captured_at.is_not(None)
                    )
                    .order_by(item.ordinal)
                )
            )
            .mappings()
            .all()
        )

    async def counters(self, order_id, *, session):
        db = _session(session)
        allocations, decisions = (
            REPLACEMENTS["allocations"],
            REPLACEMENTS["decisions"],
        )
        used = await db.scalar(
            select(func.count())
            .select_from(allocations.join(decisions))
            .where(decisions.c.order_id == order_id)
        )
        closed = await db.scalar(
            select(exists().where(MATURITY["closures"].c.order_id == order_id))
        )
        reminder = await db.scalar(
            select(JOBS.c.state).where(
                or_(JOBS.c.requested, JOBS.c.state != "ready"),
                JOBS.c.job_id == summary_job_id(order_id, "reminder"),
            )
        )
        return used, closed, reminder

    async def patch_card(self, order_id, *, session, **fields):
        await _session(session).execute(
            update(CARDS).where(CARDS.c.order_id == order_id).values(**fields)
        )

    async def claim_message(self, order_id, client_id, at, *, session):
        return await _session(session).scalar(
            update(CARDS)
            .where(
                CARDS.c.order_id == order_id,
                CARDS.c.client_id == client_id,
                CARDS.c.message_id.is_(None),
                CARDS.c.message_claimed_at.is_(None),
            )
            .values(message_claimed_at=at)
            .returning(CARDS.c.order_id)
        )

    async def adopt_message(self, order_id, client_id, message_id, *, session):
        return await _session(session).scalar(
            update(CARDS)
            .where(
                CARDS.c.order_id == order_id,
                CARDS.c.client_id == client_id,
                CARDS.c.message_id.is_(None),
                CARDS.c.message_claimed_at.is_not(None),
            )
            .values(message_id=message_id)
            .returning(CARDS.c.message_id)
        )

    async def forget_message(self, order_id, message_id, *, session):
        await _session(session).execute(
            update(CARDS)
            .where(
                CARDS.c.order_id == order_id,
                CARDS.c.message_id == message_id,
            )
            .values(message_id=None, message_claimed_at=None)
        )

    async def report_context(self, report, *, session):
        db = _session(session)
        return (
            (
                await db.execute(
                    select(
                        OrderModel.advertiser_id,
                        OrderModel.status,
                        ItemAssignmentModel.valid_to,
                        ItemAssignmentModel.creator_id,
                        CollaborationModel.state.label("work_state"),
                    )
                    .join(
                        OrderItemModel,
                        OrderItemModel.order_id == OrderModel.order_id,
                    )
                    .join(
                        ItemAssignmentModel,
                        ItemAssignmentModel.paid_item_id
                        == OrderItemModel.paid_item_id,
                    )
                    .outerjoin(
                        CollaborationModel,
                        CollaborationModel.assignment_id
                        == ItemAssignmentModel.assignment_id,
                    )
                    .where(
                        OrderModel.order_id == report["order_id"],
                        ItemAssignmentModel.assignment_id
                        == report["assignment_id"],
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def notify_reviews(self, at, *, session, limit):
        db = _session(session)
        reports = (
            (
                await db.execute(
                    select(REPORTS)
                    .where(
                        REPORTS.c.state == "review",
                        REPORTS.c.support_request_id.is_(None),
                    )
                    .order_by(REPORTS.c.created_at, REPORTS.c.report_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .all()
        )
        grouped = {}
        for row in reports:
            grouped.setdefault((row["order_id"], row["client_id"]), []).append(
                row
            )
        for (order_id, client_id), entries in grouped.items():
            request_id = await self.enqueue_review(
                order_id,
                client_id,
                str(entries[0]["report_id"]),
                [
                    {
                        "paid_item_id": str(row["paid_item_id"]),
                        "report_id": str(row["report_id"]),
                        "creator_id": str(row["creator_id"]),
                        "reason": row["review_reason"],
                    }
                    for row in entries
                ],
                at,
                session=db,
            )
            await db.execute(
                update(REPORTS)
                .where(
                    REPORTS.c.report_id.in_([r["report_id"] for r in entries])
                )
                .values(support_request_id=request_id)
            )

    async def enqueue_review(
        self, order_id, client_id, key, entries, at, *, session
    ):
        request_id = uuid5(
            NAMESPACE_URL, f"ugc:summary-review:{order_id}:{key}"
        )
        await _session(session).execute(
            insert(REQUESTS)
            .values(
                request_id=request_id,
                order_id=order_id,
                user_id=client_id,
                kind="support",
                operation_key=f"telegram-summary-review:{request_id}",
                payload_hash=request_id.hex * 2,
                payload={
                    "topic": "order_summary",
                    "order_id": str(order_id),
                    "reports": entries,
                },
                state="new",
                created_at=at,
            )
            .on_conflict_do_nothing()
        )
        return request_id

    async def order_for_position(self, paid_item_id, *, session):
        return await _session(session).scalar(
            select(OrderItemModel.order_id).where(
                OrderItemModel.paid_item_id == paid_item_id
            )
        )

    async def by_draft(self, draft_id, *, session):
        return await _session(session).scalar(
            select(CARDS.c.order_id).where(CARDS.c.draft_id == draft_id)
        )

    async def by_report(self, report_id, *, session):
        return await _session(session).scalar(
            select(REPORTS.c.order_id).where(REPORTS.c.report_id == report_id)
        )

    async def add_job(
        self,
        order_id,
        recipient_id,
        kind,
        due_at,
        *,
        session,
        report_id=None,
        requested=False,
    ):
        insert_job = insert(JOBS).values(
            job_id=summary_job_id(report_id or order_id, kind),
            order_id=order_id,
            recipient_id=recipient_id,
            kind=kind,
            state="ready",
            due_at=due_at,
            report_id=report_id,
            requested=requested,
        )
        statement = (
            insert_job.on_conflict_do_update(
                index_elements=[JOBS.c.job_id],
                set_={"requested": True, "due_at": due_at},
                where=(JOBS.c.state == "ready") & ~JOBS.c.requested,
            )
            if requested
            else insert_job.on_conflict_do_nothing()
        )
        return await _session(session).scalar(
            statement.returning(JOBS.c.job_id)
        )

    async def assignment_report_state(self, assignment_id, *, session):
        return await _session(session).scalar(
            select(report_state())
            .select_from(
                REPORTS.outerjoin(
                    REQUESTS,
                    REQUESTS.c.request_id == REPORTS.c.support_request_id,
                )
            )
            .where(REPORTS.c.assignment_id == assignment_id)
        )

    async def add_report(
        self, order_id, client_id, position, reason, at, *, session
    ):
        db = _session(session)
        report_id = uuid4()
        report_id = await db.scalar(
            insert(REPORTS)
            .values(
                report_id=report_id,
                order_id=order_id,
                client_id=client_id,
                assignment_id=position["assignment_id"],
                creator_id=position["creator_id"],
                paid_item_id=position["paid_item_id"],
                reason=reason,
                created_at=at,
                state="queued" if reason == "no_answer" else "review",
                review_reason=None if reason == "no_answer" else reason,
            )
            .on_conflict_do_nothing(index_elements=[REPORTS.c.assignment_id])
            .returning(REPORTS.c.report_id)
        )
        if report_id is not None and reason == "no_answer":
            await self.add_job(
                order_id,
                position["creator_id"],
                "creator",
                at,
                session=db,
                report_id=report_id,
            )
        return report_id is not None

    async def report(self, report_id, *, session, lock=False):
        query = select(REPORTS).where(REPORTS.c.report_id == report_id)
        if lock:
            query = query.with_for_update()
        return (await _session(session).execute(query)).mappings().one_or_none()

    async def set_report(self, report_id, *, session, **fields):
        await _session(session).execute(
            update(REPORTS)
            .where(REPORTS.c.report_id == report_id)
            .values(**fields)
        )

    async def discover(self, at, *, session, limit):
        db = _session(session)
        # Show the entire card once the first paid position is due.
        due = exists().where(
            OrderItemModel.order_id == OrderModel.order_id,
            OrderItemModel.captured_at.is_not(None),
            OrderItemModel.selection_due_at <= at,
        ) | exists().where(
            CollaborationModel.order_id == OrderModel.order_id,
            CollaborationModel.due_at <= at,
            ItemAssignmentModel.assignment_id
            == CollaborationModel.assignment_id,
            ItemAssignmentModel.valid_to.is_(None),
        )
        rows = (
            await db.execute(
                select(OrderModel.order_id, OrderModel.advertiser_id)
                .join(UserModel, UserModel.user_id == OrderModel.advertiser_id)
                .where(
                    *funded_order(),
                    OrderModel.status == OrderStatus.ACTIVE,
                    UserModel.telegram_id.op("~")(r"^[1-9][0-9]*$"),
                    UserModel.status == "active",
                    due,
                    ~exists().where(
                        JOBS.c.order_id == OrderModel.order_id,
                        JOBS.c.kind == "summary",
                    ),
                    ~exists().where(
                        CARDS.c.order_id == OrderModel.order_id,
                        or_(
                            CARDS.c.message_id.is_not(None),
                            CARDS.c.closed_at.is_not(None),
                        ),
                    ),
                )
                .order_by(OrderModel.created_at, OrderModel.order_id)
                .limit(limit)
            )
        ).all()
        for order_id, client_id in rows:
            await self.add_job(order_id, client_id, "summary", at, session=db)

    async def claim_jobs(self, at, *, session, limit):
        db = _session(session)
        await db.execute(
            update(JOBS)
            .where(
                JOBS.c.state == "sending",
                JOBS.c.claimed_at <= at - timedelta(minutes=5),
            )
            .values(state="unknown")
        )
        rows = (
            (
                await db.execute(
                    select(JOBS)
                    .where(JOBS.c.state == "ready", JOBS.c.due_at <= at)
                    .order_by(JOBS.c.due_at, JOBS.c.job_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .all()
        )
        if rows:
            await db.execute(
                update(JOBS)
                .where(JOBS.c.job_id.in_([r["job_id"] for r in rows]))
                .values(state="sending", claimed_at=at)
            )
        return rows

    async def finish_job(self, job_id, state, reference, at, *, session):
        return await _session(session).scalar(
            update(JOBS)
            .where(
                JOBS.c.job_id == job_id,
                JOBS.c.state == "sending",
            )
            .values(
                state=state,
                provider_reference=reference,
                delivered_at=at if state == "sent" else None,
            )
            .returning(JOBS.c.job_id)
        )

    async def lock_positions(self, order_id, *, session):
        return list(
            await _session(session).scalars(
                select(OrderItemModel.paid_item_id)
                .where(
                    OrderItemModel.order_id == order_id,
                    OrderItemModel.selection_state.in_(("paid", "delivered")),
                )
                .order_by(OrderItemModel.paid_item_id)
                .with_for_update()
            )
        )

    async def claim_closing(self, order_id, at, *, session):
        return await _session(session).scalar(
            update(CARDS)
            .where(
                CARDS.c.order_id == order_id,
                CARDS.c.closed_at.is_(None),
                or_(
                    CARDS.c.reviewed_at.is_(None),
                    CARDS.c.reviewed_at <= at - timedelta(minutes=5),
                ),
            )
            .values(reviewed_at=at)
            .returning(CARDS.c.order_id)
        )

    async def closing_candidates(self, at, *, session, limit):
        return (
            await _session(session).execute(
                select(CARDS.c.order_id, CARDS.c.client_id)
                .where(
                    CARDS.c.closed_at.is_(None),
                    or_(
                        CARDS.c.reviewed_at.is_(None),
                        CARDS.c.reviewed_at <= at - timedelta(minutes=5),
                    ),
                )
                .order_by(
                    CARDS.c.reviewed_at.asc().nulls_first(), CARDS.c.order_id
                )
                .limit(limit)
            )
        ).all()

    async def expired(self, at, *, session, limit):
        return (
            (
                await _session(session).execute(
                    select(REPORTS)
                    .outerjoin(JOBS, JOBS.c.report_id == REPORTS.c.report_id)
                    .where(
                        or_(
                            and_(
                                REPORTS.c.state == "waiting",
                                REPORTS.c.answer_due_at <= at,
                            ),
                            and_(
                                REPORTS.c.state == "queued",
                                JOBS.c.state.in_(
                                    ("failed", "unknown", "obsolete")
                                ),
                            ),
                        )
                    )
                    .order_by(
                        REPORTS.c.answer_due_at.asc().nulls_first(),
                        REPORTS.c.created_at,
                        REPORTS.c.report_id,
                    )
                    .limit(limit)
                )
            )
            .mappings()
            .all()
        )

    async def user(self, user_id, *, session):
        return await _session(session).get(UserModel, user_id)
