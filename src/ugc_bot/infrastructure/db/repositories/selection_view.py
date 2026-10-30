"""Consistent, own-client reads; no wallet creation or queue mutation."""

from sqlalchemy import exists, select, text

from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    FinancialPolicyVersionModel,
    ItemAssignmentModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.paid_selection_models import INTERESTS, JOBS
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    decode_policy_version,
)
from ugc_bot.infrastructure.db.selection_delivery_models import ACCEPTED
from ugc_bot.infrastructure.db.selection_maturity_models import (
    TABLES as MATURITY_TABLES,
)


async def _rows(db, statement):
    return (await db.execute(statement)).mappings().all()


class SqlAlchemySelectionViewRepository:
    async def begin_snapshot(self, *, session):
        await _session(session).execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )

    async def view(self, order_id, client_id, *, session, principal=None):
        db = _session(session)
        user = (
            await db.execute(
                select(
                    UserModel.user_id,
                    UserModel.status,
                    UserModel.telegram_id,
                    UserModel.max_id,
                )
                .where(UserModel.user_id == client_id)
                .execution_options(autoflush=False)
            )
        ).one_or_none()
        require_current_principal(
            principal,
            client_id,
            user.user_id if user else None,
            user.telegram_id if user else None,
            user.max_id if user else None,
        )
        if user is None or user.status not in (
            "active",
            "pause",
            "bot_blocked",
        ):
            raise PermissionError("selection_client_inactive")
        if not await db.scalar(
            select(exists().where(AdvertiserProfileModel.user_id == client_id))
        ):
            raise PermissionError("selection_client_role_required")
        order = (
            (
                await db.execute(
                    select(OrderModel.__table__).where(
                        OrderModel.order_id == order_id,
                        OrderModel.advertiser_id == client_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if order is None:
            raise LookupError("selection_order_not_found")
        if not order["financial_version"]:
            raise ValueError("selection_order_has_no_financial_version")
        installed = await db.scalar(
            text(
                "SELECT to_regclass('paid_selection_interests') IS NOT NULL "
                "AND to_regclass('paid_selection_delivery_jobs') IS NOT NULL "
                "AND to_regclass('paid_selection_accepted_deliveries') "
                "IS NOT NULL"
            )
        )
        if not installed:
            raise ValueError("selection_history_unavailable")
        items = await _rows(
            db,
            select(OrderItemModel.__table__)
            .where(OrderItemModel.order_id == order_id)
            .order_by(OrderItemModel.ordinal),
        )
        assignments = await _rows(
            db,
            select(ItemAssignmentModel.__table__)
            .join(
                OrderItemModel,
                OrderItemModel.paid_item_id == ItemAssignmentModel.paid_item_id,
            )
            .where(
                OrderItemModel.order_id == order_id,
                ItemAssignmentModel.valid_to.is_(None),
            ),
        )
        interests = await _rows(
            db,
            select(INTERESTS).where(
                INTERESTS.c.order_id == order_id,
                INTERESTS.c.client_id == client_id,
            ),
        )
        jobs = await _rows(db, select(JOBS).where(JOBS.c.order_id == order_id))
        deliveries = await _rows(
            db,
            select(ACCEPTED)
            .where(
                ACCEPTED.c.order_id == order_id,
                ACCEPTED.c.client_id == client_id,
            )
            .order_by(ACCEPTED.c.accepted_at),
        )
        by_assignment = {
            row["assignment_id"]: row for row in interests if row["accepted"]
        }
        by_interest = {row["interest_id"]: row for row in interests}
        for fact in deliveries:
            interest = by_interest.get(fact["interest_id"])
            if interest is None or any(
                fact[key] != interest[key]
                for key in (
                    "order_id",
                    "client_id",
                    "creator_id",
                    "paid_item_id",
                    "assignment_id",
                    "payment_id",
                    "capture_event_id",
                    "instagram_user_id",
                )
            ):
                raise ValueError("selection_delivery_scope_mismatch")
        by_job = {row["interest_id"]: row for row in jobs}
        by_item = {row["paid_item_id"]: row for row in assignments}
        positions = [
            self._position(
                item,
                by_item.get(item["paid_item_id"]),
                by_assignment,
                by_interest,
                by_job,
                deliveries,
            )
            for item in items
        ]
        closure_policy = await self._closure_policy(
            db,
            order_id,
            order["financial_version"],
            items,
            deliveries,
            positions,
        )
        return dict(
            order_id=order_id,
            **(
                {"image_token": order["product_photo_file_id"].split(":", 1)[1]}
                if (order["product_photo_file_id"] or "").startswith(
                    "order-image:"
                )
                else {}
            ),
            policy_version=order["financial_version"],
            **(
                {"closure_policy": closure_policy}
                if closure_policy is not None
                else {}
            ),
            positions=positions,
            waitlist_count=sum(not row["accepted"] for row in interests),
        )

    @staticmethod
    async def _closure_policy(
        db, order_id, policy_version, items, deliveries, positions
    ):
        stored_policy = await db.get(
            FinancialPolicyVersionModel, policy_version
        )
        policy = None
        if (
            stored_policy is not None
            and isinstance(stored_policy.rules, dict)
            and "maturity_mode" in stored_policy.rules
        ):
            policy = decode_policy_version(stored_policy)
        raw_rules = (
            items[0]["quote_payload"].get("refund_rules") if items else None
        )
        closure_policy = None
        if raw_rules is not None:
            rules = RefundRules.from_document(raw_rules)
            closures = MATURITY_TABLES["closures"]
            closed_at = await db.scalar(
                select(closures.c.closed_at).where(
                    closures.c.order_id == order_id
                )
            )
            components = Base.metadata.tables[
                "financial_refund_component_applications"
            ]
            refunds = await _rows(
                db,
                select(components).where(
                    components.c.paid_item_id.in_(
                        [item["paid_item_id"] for item in items]
                    ),
                    components.c.component == "selection",
                ),
            )
            refunded = {
                item["paid_item_id"]
                for item in items
                if sum(
                    row["refund_minor"]
                    for row in refunds
                    if row["paid_item_id"] == item["paid_item_id"]
                )
                == item["selection_minor"]
            }
            for position in positions:
                if position["paid_item_id"] in refunded:
                    position["delivery_state"] = "refunded"
            resolved = all(
                item["paid_item_id"] in refunded
                or any(
                    fact["paid_item_id"] == item["paid_item_id"]
                    for fact in deliveries
                )
                for item in items
            )
            closure_policy = dict(
                mode=rules.selection_closure_mode,
                refund_window_seconds=rules.selection_refund_window_seconds,
                anchor=rules.selection_refund_window_anchor,
                closed_at=closed_at,
                can_close=rules.selection_closure_mode == "manual"
                and closed_at is None
                and resolved,
            )
        if policy is not None and policy.maturity_mode == "per_item_v1":
            closure_policy = dict(
                mode="per_item_v1",
                refund_window_seconds=int(
                    policy.selection_refund_window.total_seconds()
                ),
                anchor="item_delivered",
                closed_at=None,
                can_close=False,
            )
        return closure_policy

    @staticmethod
    def _position(
        item, assignment, by_assignment, by_interest, by_job, deliveries
    ):
        current_id = assignment["assignment_id"] if assignment else None
        interest = by_assignment.get(current_id)
        job = by_job.get(interest["interest_id"]) if interest else None
        facts = [
            fact
            for fact in deliveries
            if fact["paid_item_id"] == item["paid_item_id"]
        ]
        current_fact = next(
            (fact for fact in facts if fact["assignment_id"] == current_id),
            None,
        )
        state = (
            job["state"] if job else "unknown" if assignment else "unassigned"
        )
        if item["selection_state"] in ("refunded", "cancelled"):
            # The correction producer must supply an authoritative fact before
            # a mutable projection alone can be described as a real refund.
            state = "unknown"
        elif current_fact is not None:
            state = "accepted"
        elif (
            state == "accepted"
            or item["selection_state"] == "delivered"
            and not facts
        ):
            state = "unknown"
        history = [
            dict(
                assignment_id=fact["assignment_id"],
                creator_id=fact["creator_id"],
                instagram_url=by_interest[fact["interest_id"]]["instagram_url"],
                accepted_at=fact["accepted_at"],
                current=fact["assignment_id"] == current_id,
            )
            for fact in facts
        ]
        return dict(
            ordinal=item["ordinal"],
            paid_item_id=item["paid_item_id"],
            currency=item["currency"],
            selection_minor=item["selection_minor"],
            accompaniment_minor=item["accompaniment_minor"],
            assignment_id=current_id,
            creator_id=assignment["creator_id"] if assignment else None,
            instagram_url=interest["instagram_url"] if interest else None,
            delivery_state=state,
            current=assignment is not None,
            delivered_at=current_fact["accepted_at"] if current_fact else None,
            fulfilled_at=facts[0]["accepted_at"] if facts else None,
            deliveries=history,
        )
