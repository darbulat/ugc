"""User/wallet, order/funding/history, then item locks for replacements."""

from datetime import timedelta

from sqlalchemy import exists, func, insert, select, text, update

from ugc_bot.application.replacement_ports import (
    ReplacementCandidate,
    ReplacementScope,
)
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.collaboration_models import (
    CollaborationEventModel,
    CollaborationModel,
)
from ugc_bot.infrastructure.db.identity_history_schema import (
    HISTORY_SNAPSHOT_LOCK_SQL,
)
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OrderItemModel,
    OrderModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_summary_models import JOBS as SUMMARY_JOBS
from ugc_bot.infrastructure.db.order_summary_models import REPORTS
from ugc_bot.infrastructure.db.paid_selection_models import INTERESTS
from ugc_bot.infrastructure.db.replacement_models import TABLES
from ugc_bot.infrastructure.db.repositories.collaborations import (
    SqlAlchemyCollaborationRepository,
)
from ugc_bot.infrastructure.db.repositories.correction_funding import (
    require_forward_clear,
)
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
    _session,
)
from ugc_bot.infrastructure.db.repositories.item_assignments import (
    SqlAlchemyItemAssignmentRepository,
)
from ugc_bot.infrastructure.db.repositories.paid_selection import (
    SqlAlchemyPaidSelectionRepository,
)


async def _rows(db, table, **filters):
    return (
        (await db.execute(select(table).filter_by(**filters))).mappings().all()
    )


class SqlAlchemyReplacementRepository:
    async def queue(self, page, *, session):
        requests, decisions = TABLES["requests"], TABLES["decisions"]
        rows = (
            (
                await _session(session).execute(
                    select(requests)
                    .outerjoin(
                        decisions,
                        decisions.c.request_id == requests.c.request_id,
                    )
                    .where(decisions.c.replacement_id.is_(None))
                    .order_by(requests.c.requested_at, requests.c.request_id)
                    .offset(page * 20)
                    .limit(21)
                )
            )
            .mappings()
            .all()
        )
        return dict(
            page=page,
            has_more=len(rows) > 20,
            entries=[
                dict(
                    request_id=str(row["request_id"]),
                    paid_item_id=str(row["paid_item_id"]),
                    order_id=str(row["order_id"]),
                    reason=row["reason"],
                    requested_at=row["requested_at"].isoformat(),
                )
                for row in rows[:20]
            ],
        )

    async def load_scope(self, item_id, *, session):
        db = _session(session)
        item = await db.get(OrderItemModel, item_id, populate_existing=True)
        if item is None:
            raise ValueError("replacement_position_not_found")
        order = await db.get(OrderModel, item.order_id, populate_existing=True)
        if order is None or order.financial_version is None:
            raise ValueError("replacement_paid_capture_required")
        capture = await SqlAlchemyPaidSelectionRepository()._funding(
            item.order_id, session=db
        )
        captured = next(
            (p for p in capture.items if p.paid_item_id == item_id), None
        )
        if (
            captured is None
            or captured.selection_minor != capture.policy.selection_minor
            or capture.client_id != order.advertiser_id
        ):
            raise ValueError("replacement_paid_capture_required")
        assignments = await _rows(
            db, ItemAssignmentModel.__table__, paid_item_id=item_id
        )
        current = [a for a in assignments if a["valid_to"] is None]
        if len(current) != 1:
            raise ValueError("replacement_current_assignment_required")
        current = current[0]
        managers = tuple(
            await db.scalars(
                select(ManagerOrderModel.user_id)
                .join(UserModel, UserModel.user_id == ManagerOrderModel.user_id)
                .where(
                    ManagerOrderModel.order_id == order.order_id,
                    UserModel.status.in_(("active", "pause")),
                )
                .order_by(ManagerOrderModel.user_id)
            )
        )
        events = await db.scalars(
            select(CollaborationEventModel.result_payload).where(
                CollaborationEventModel.assignment_id.in_(
                    [a["assignment_id"] for a in assignments]
                )
            )
        )
        completed = any(
            payload.get("collaboration", {}).get("success_final_at") is not None
            for payload in events
        )
        count = await db.scalar(
            select(func.count())
            .select_from(TABLES["allocations"])
            .join(
                TABLES["decisions"],
                TABLES["decisions"].c.replacement_id
                == TABLES["allocations"].c.replacement_id,
            )
            .where(TABLES["decisions"].c.order_id == order.order_id)
        )
        return ReplacementScope(
            item_id,
            order.order_id,
            capture.client_id,
            capture.payment_id,
            capture.event_id,
            capture.policy.version,
            capture.captured_at,
            capture.source_hash,
            len(capture.items),
            item.selection_state,
            order.status == OrderStatus.ACTIVE,
            current["assignment_id"],
            current["version"],
            current["creator_id"],
            current["manager_id"],
            current["valid_from"],
            tuple(sorted((a["assignment_id"] for a in assignments), key=str)),
            tuple(sorted({a["creator_id"] for a in assignments}, key=str)),
            managers,
            captured.accompaniment_minor == capture.policy.accompaniment_minor,
            count,
            completed,
        )

    async def lock_scope(self, scope, *, session):
        db = _session(session)
        await SqlAlchemyFinancialItemRepository().lock_order(
            scope.order_id, session=db
        )
        await db.execute(
            select(OrderModel.order_id)
            .where(OrderModel.order_id == scope.order_id)
            .with_for_update()
        )
        await db.execute(
            select(PaymentModel.payment_id)
            .where(PaymentModel.order_id == scope.order_id)
            .with_for_update()
        )
        await db.execute(
            select(ManagerOrderModel.user_id)
            .where(ManagerOrderModel.order_id == scope.order_id)
            .order_by(ManagerOrderModel.user_id)
            .with_for_update()
        )
        await db.execute(text(HISTORY_SNAPSHOT_LOCK_SQL))
        for item in await db.scalars(
            select(OrderItemModel.paid_item_id)
            .where(OrderItemModel.order_id == scope.order_id)
            .order_by(OrderItemModel.paid_item_id)
        ):
            await db.execute(
                select(OrderItemModel.paid_item_id)
                .where(OrderItemModel.paid_item_id == item)
                .with_for_update()
            )

    async def load_actor(self, actor_id, *, session):
        return await SqlAlchemyCollaborationRepository().load_actor(
            actor_id, session=session
        )

    async def candidate(self, interest_id, *, session):
        db = _session(session)
        rows = await _rows(db, INTERESTS, interest_id=interest_id)
        if not rows:
            return None
        row = rows[0]
        profile = await db.get(
            BloggerProfileModel, row["creator_id"], populate_existing=True
        )
        user = await db.get(
            UserModel, row["creator_id"], populate_existing=True
        )
        used = row["accepted"] or bool(
            await db.scalar(
                select(
                    exists().where(
                        TABLES["allocations"].c.candidate_interest_id
                        == interest_id
                    )
                )
            )
        )
        verified = (
            profile is not None
            and user is not None
            and str(user.status) in ("active", "pause")
            and profile.confirmed
            and profile.instagram_user_id
            and profile.instagram_user_id.strip() == row["instagram_user_id"]
            and profile.instagram_url == row["instagram_url"]
        )
        return ReplacementCandidate(
            *(
                row[key]
                for key in (
                    "interest_id",
                    "order_id",
                    "creator_id",
                    "payment_id",
                    "capture_event_id",
                    "policy_version",
                    "confirmed_at",
                    "instagram_user_id",
                    "instagram_url",
                )
            ),
            bool(verified),
            bool(used),
        )

    async def get_command(self, actor_id, key, *, session):
        db = _session(session)
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"replacement-command:{actor_id}:{key}"},
        )
        rows = await _rows(
            db, TABLES["commands"], actor_id=actor_id, operation_key=key
        )
        return (rows[0]["payload_hash"], rows[0]["result"]) if rows else None

    async def save_command(self, actor_id, key, digest, result, *, session):
        await _session(session).execute(
            insert(TABLES["commands"]).values(
                actor_id=actor_id,
                operation_key=key,
                payload_hash=digest,
                result=result,
            )
        )

    async def append_request(self, fact, *, session):
        await _session(session).execute(
            insert(TABLES["requests"]).values(**fact)
        )

    async def request(self, request_id, *, session):
        rows = await _rows(
            _session(session), TABLES["requests"], request_id=request_id
        )
        return dict(rows[0]) if rows else None

    async def decision(self, request_id, *, session):
        rows = await _rows(
            _session(session), TABLES["decisions"], request_id=request_id
        )
        return dict(rows[0]) if rows else None

    async def append_decision(self, fact, *, session):
        await _session(session).execute(
            insert(TABLES["decisions"]).values(**fact)
        )

    async def authorize_automatic(
        self, report_id, request_id, scope, now, *, session
    ):
        db = _session(session)
        report = (
            (
                await db.execute(
                    select(REPORTS)
                    .where(REPORTS.c.report_id == report_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        work = await db.get(
            CollaborationModel, scope.assignment_id, populate_existing=True
        )
        if (
            report is None
            or report["assignment_id"] != scope.assignment_id
            or report["client_id"] != scope.client_id
            or report["creator_id"] != scope.creator_id
            or report["reason"] != "no_answer"
            or report["state"] != "waiting"
            or report["answer_due_at"] is None
            or report["answer_due_at"] > now
            or report["automatic_request_id"] is not None
            or (
                work is not None
                and work.state
                not in ("assigned", "in_progress", "unconfirmed_expired")
            )
        ):
            raise ValueError("automatic_replacement_report_unavailable")
        if not await db.scalar(
            select(
                exists().where(
                    SUMMARY_JOBS.c.report_id == report_id,
                    SUMMARY_JOBS.c.kind == "creator",
                    SUMMARY_JOBS.c.state == "sent",
                    SUMMARY_JOBS.c.order_id == scope.order_id,
                    SUMMARY_JOBS.c.recipient_id == scope.creator_id,
                    SUMMARY_JOBS.c.delivered_at
                    == report["answer_due_at"] - timedelta(hours=24),
                    SUMMARY_JOBS.c.provider_reference.is_not(None),
                )
            )
        ):
            raise ValueError("automatic_replacement_notice_required")
        await db.execute(
            update(REPORTS)
            .where(REPORTS.c.report_id == report_id)
            .values(automatic_request_id=request_id)
        )

    async def finish_automatic(self, report_id, replacement_id, *, session):
        await _session(session).execute(
            update(REPORTS)
            .where(REPORTS.c.report_id == report_id)
            .values(state="replaced", replacement_id=replacement_id)
        )

    async def automatic_candidates(self, order_id, *, session):
        return list(
            await _session(session).scalars(
                select(INTERESTS.c.interest_id)
                .where(
                    INTERESTS.c.order_id == order_id,
                    INTERESTS.c.accepted.is_(False),
                    ~exists().where(
                        TABLES["allocations"].c.candidate_interest_id
                        == INTERESTS.c.interest_id
                    ),
                    ~exists().where(
                        ItemAssignmentModel.creator_id
                        == INTERESTS.c.creator_id,
                        ItemAssignmentModel.paid_item_id
                        == OrderItemModel.paid_item_id,
                        OrderItemModel.order_id == order_id,
                    ),
                )
                .order_by(INTERESTS.c.confirmed_at, INTERESTS.c.interest_id)
            )
        )

    async def replace_assignment(
        self, scope, candidate, manager_id, actor_id, reason, at, *, session
    ):
        row = await SqlAlchemyItemAssignmentRepository().replace(
            paid_item_id=scope.paid_item_id,
            expected_version=scope.assignment_version,
            creator_id=candidate.creator_id,
            manager_id=manager_id,
            actor_id=actor_id,
            reason=reason,
            at=at,
            session=session,
        )
        return row.assignment_id

    async def append_allocation(self, fact, *, session):
        values = dict(
            fact, movement_ids=[str(value) for value in fact["movement_ids"]]
        )
        await _session(session).execute(
            insert(TABLES["allocations"]).values(**values)
        )

    async def require_clear(self, item_id, *, session):
        await require_forward_clear(item_id, session=session)

    async def view(self, scope, *, admin, session):
        db = _session(session)
        candidates = await _rows(
            db, INTERESTS, order_id=scope.order_id, accepted=False
        )
        reserve = []
        for row in candidates[:100]:
            candidate = await self.candidate(row["interest_id"], session=db)
            if candidate.verified and not candidate.used:
                reserve.append(
                    dict(
                        interest_id=str(candidate.interest_id),
                        creator_id=str(candidate.creator_id),
                        instagram_url=candidate.instagram_url,
                    )
                )
        requests = TABLES["requests"]
        decisions = TABLES["decisions"]
        allocations = TABLES["allocations"]
        rows = (
            await db.execute(
                select(
                    requests,
                    decisions.c.replacement_id,
                    decisions.c.action,
                    allocations.c.assignment_id,
                )
                .outerjoin(
                    decisions, decisions.c.request_id == requests.c.request_id
                )
                .outerjoin(
                    allocations,
                    allocations.c.replacement_id == decisions.c.replacement_id,
                )
                .where(requests.c.paid_item_id == scope.paid_item_id)
                .order_by(requests.c.requested_at.desc())
                .limit(100)
            )
        ).mappings()
        history = [
            dict(
                request_id=str(row["request_id"]),
                version=2 if row["action"] else 1,
                state={"approve": "approved", "reject": "rejected"}.get(
                    row["action"], "pending"
                ),
                reason_code=row["reason_code"],
                reason=row["reason"],
                evidence_reference=row["evidence_reference"],
                old_assignment_version=row["old_assignment_version"],
                candidate_interest_id=str(row["candidate_interest_id"]),
                replacement_id=str(row["replacement_id"])
                if row["replacement_id"]
                else None,
                current=row["assignment_id"] == scope.assignment_id,
            )
            for row in rows
        ]
        return dict(candidates=reserve, history=history)

    async def allocation(self, replacement_id, *, session):
        rows = await _rows(
            _session(session),
            TABLES["allocations"],
            replacement_id=replacement_id,
        )
        return dict(rows[0]) if rows else None

    async def contact(self, scope, *, session):
        db = _session(session)
        user = await db.get(UserModel, scope.creator_id, populate_existing=True)
        profile = await db.get(
            BloggerProfileModel, scope.creator_id, populate_existing=True
        )
        if (
            profile is None
            or user is None
            or not profile.confirmed
            or str(user.status) not in ("active", "pause")
        ):
            raise ValueError("replacement_contact_unavailable")
        return dict(
            creator_id=str(scope.creator_id),
            display_name=user.username,
            telegram=user.telegram,
            phone=profile.phone,
            instagram_url=profile.instagram_url,
        )

    async def append_contact(self, fact, *, session):
        await _session(session).execute(
            insert(TABLES["contacts"]).values(**fact)
        )
