"""Read-only aggregates with current scope and explicit source semantics."""

from collections import Counter
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import exists, select, text

from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.infrastructure.db.collaboration_models import (
    CollaborationEventModel,
    CollaborationModel,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    InteractionModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.paid_selection_models import INTERESTS
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.selection_delivery_models import (
    ACCEPTED,
    OUTCOMES,
)


async def _rows(db, statement):
    return (await db.execute(statement)).mappings().all()


class SqlAlchemyCampaignSummaryRepository:
    async def begin_snapshot(self, *, session):
        await _session(session).execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )

    async def view(self, order_id, actor_id, *, session, principal=None):
        db = _session(session)
        user = (
            await db.execute(
                select(
                    UserModel.user_id,
                    UserModel.status,
                    UserModel.telegram_id,
                    UserModel.max_id,
                )
                .where(UserModel.user_id == actor_id)
                .execution_options(autoflush=False)
            )
        ).one_or_none()
        require_current_principal(
            principal,
            actor_id,
            user.user_id if user else None,
            user.telegram_id if user else None,
            user.max_id if user else None,
        )
        if user is None or user.status not in (
            "active",
            "pause",
            "bot_blocked",
        ):
            raise PermissionError("summary_actor_inactive")
        order = (
            (
                await db.execute(
                    select(OrderModel.__table__).where(
                        OrderModel.order_id == order_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if order is None:
            raise LookupError("summary_not_found")
        is_client = order["advertiser_id"] == actor_id and await db.scalar(
            select(exists().where(AdvertiserProfileModel.user_id == actor_id))
        )
        if not is_client and not await db.scalar(
            select(
                exists().where(
                    ManagerOrderModel.order_id == order_id,
                    ManagerOrderModel.user_id == actor_id,
                )
            )
        ):
            raise LookupError("summary_not_found")
        role = "client" if is_client else "manager"
        if order["financial_version"]:
            result = await self._financial(db, order, actor_id, role)
        else:
            result = await self._legacy(db, order, actor_id, role)
        return dict(result, order_id=order_id, role=role)

    async def _financial(self, db, order, actor_id, role):
        installed = await db.scalar(
            text(
                "SELECT to_regclass('financial_collaboration_events') "
                "IS NOT NULL AND "
                "to_regclass('financial_collaborations') IS NOT NULL AND "
                "to_regclass('paid_selection_accepted_deliveries') IS NOT NULL "
                "AND to_regclass('paid_selection_interests') IS NOT NULL "
                "AND to_regclass('paid_selection_delivery_outcomes') "
                "IS NOT NULL"
            )
        )
        if not installed:
            raise ValueError("summary_history_unavailable")
        items = await _rows(
            db,
            select(OrderItemModel.__table__).where(
                OrderItemModel.order_id == order["order_id"]
            ),
        )
        assignments = await _rows(
            db,
            select(ItemAssignmentModel.__table__)
            .join(
                OrderItemModel,
                OrderItemModel.paid_item_id == ItemAssignmentModel.paid_item_id,
            )
            .where(
                OrderItemModel.order_id == order["order_id"],
                ItemAssignmentModel.valid_to.is_(None),
            ),
        )
        by_item = {a["paid_item_id"]: a for a in assignments}
        if role == "manager":
            items = [
                i
                for i in items
                if by_item.get(i["paid_item_id"], {}).get("manager_id")
                == actor_id
            ]
        assignment_ids = [
            by_item[i["paid_item_id"]]["assignment_id"]
            for i in items
            if i["paid_item_id"] in by_item
        ]
        works = await _rows(
            db,
            select(CollaborationModel.__table__).where(
                CollaborationModel.assignment_id.in_(assignment_ids)
            ),
        )
        events = await _rows(
            db,
            select(CollaborationEventModel.__table__).where(
                CollaborationEventModel.assignment_id.in_(assignment_ids)
            ),
        )
        work_by_id = {w["assignment_id"]: w for w in works}
        latest: dict[UUID, Mapping[str, Any]] = {}
        for event in events:
            key = event["assignment_id"]
            if key not in latest or event["version"] > latest[key]["version"]:
                latest[key] = event
        deliveries = await _rows(
            db,
            select(ACCEPTED).where(
                ACCEPTED.c.order_id == order["order_id"],
                ACCEPTED.c.client_id == order["advertiser_id"],
                ACCEPTED.c.assignment_id.in_(assignment_ids),
            ),
        )
        contact_count = await self._contact_count(db, deliveries, by_item)
        counts: Counter[str] = Counter()
        for item in items:
            assignment = by_item.get(item["paid_item_id"])
            if assignment is None:
                state = "unassigned"
            else:
                work = work_by_id.get(assignment["assignment_id"])
                event = latest.get(assignment["assignment_id"])
                state = self._work_state(order, item, assignment, work, event)
            counts[state] += 1
        return dict(
            source="financial_positions",
            total=len(items),
            states=dict(sorted(counts.items())),
            contact_accepted=contact_count,
        )

    @staticmethod
    async def _contact_count(db, deliveries, by_item):
        interests = await _rows(
            db,
            select(INTERESTS).where(
                INTERESTS.c.interest_id.in_(
                    [d["interest_id"] for d in deliveries]
                )
            ),
        )
        by_interest = {i["interest_id"]: i for i in interests}
        outcomes = await _rows(
            db,
            select(OUTCOMES).where(
                OUTCOMES.c.outcome_id.in_([d["outcome_id"] for d in deliveries])
            ),
        )
        by_outcome = {o["outcome_id"]: o for o in outcomes}
        for delivery in deliveries:
            interest = by_interest.get(delivery["interest_id"])
            outcome = by_outcome.get(delivery["outcome_id"])
            assignment = by_item.get(delivery["paid_item_id"])
            if (
                interest is None
                or not interest["accepted"]
                or assignment is None
                or assignment["assignment_id"] != delivery["assignment_id"]
                or assignment["creator_id"] != delivery["creator_id"]
                or any(
                    interest[k] != delivery[k]
                    for k in (
                        "order_id",
                        "client_id",
                        "creator_id",
                        "paid_item_id",
                        "assignment_id",
                        "payment_id",
                        "capture_event_id",
                        "instagram_user_id",
                    )
                )
                or outcome is None
                or outcome["kind"] != "transport"
                or outcome["status"] != "accepted"
                or not outcome["applied"]
                or any(
                    outcome[k] != delivery[k]
                    for k in (
                        "job_id",
                        "attempt_id",
                        "order_id",
                        "provider_reference",
                    )
                )
            ):
                raise ValueError("summary_delivery_scope_mismatch")
        return len(deliveries)

    @staticmethod
    def _work_state(order, item, assignment, work, event):
        if work is None:
            return "not_configured"
        if event is None or (
            work["version"] != event["version"]
            or work["record_payload"] != event["result_payload"]
            or work["order_id"] != order["order_id"]
            or work["paid_item_id"] != item["paid_item_id"]
            or work["client_id"] != order["advertiser_id"]
            or work["creator_id"] != assignment["creator_id"]
            or work["manager_id"] != assignment["manager_id"]
            or work["policy_version"] != item["policy_version"]
            or work["record_payload"].get("collaboration", {}).get("state")
            != work["state"]
        ):
            return "unknown"
        return work["state"]

    async def _legacy(self, db, order, actor_id, role):
        statement = (
            select(InteractionModel.__table__)
            .where(
                InteractionModel.order_id == order["order_id"],
                InteractionModel.advertiser_id == order["advertiser_id"],
                InteractionModel.status != "deleted",
            )
            .order_by(
                InteractionModel.updated_at, InteractionModel.interaction_id
            )
        )
        if role == "manager":
            statement = statement.join(
                OfferDispatchModel,
                (OfferDispatchModel.order_id == InteractionModel.order_id)
                & (
                    OfferDispatchModel.blogger_id == InteractionModel.blogger_id
                ),
            ).where(
                OfferDispatchModel.manager_id == actor_id,
                OfferDispatchModel.in_offer.is_(True),
                OfferDispatchModel.accepted.is_(True),
            )
        interactions = await _rows(db, statement)
        unique = {i["blogger_id"]: i for i in interactions}
        allowed = {"pending", "ok", "no_deal", "issue"}
        counts = Counter(
            "legacy_" + (i["status"] if i["status"] in allowed else "unknown")
            for i in unique.values()
        )
        return dict(
            source="legacy_feedback",
            total=len(unique),
            states=dict(sorted(counts.items())),
            contact_accepted=None,
        )
