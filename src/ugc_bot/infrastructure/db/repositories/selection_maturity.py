"""Selection schedules derive from actual immutable delivery/refund facts."""

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.application.selection_maturity_ports import (
    SelectionClosure,
    SelectionMaturitySource,
    SelectionPosition,
    SelectionSnapshot,
)
from ugc_bot.application.services.correction_funding_guard import (
    LiveCorrectionFundingGuard,
)
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel
from ugc_bot.infrastructure.db.repositories.collaborations import (
    SqlAlchemyCollaborationRepository,
)
from ugc_bot.infrastructure.db.repositories.corrections import (
    SqlAlchemyCorrectionRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
    _session,
)
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    decode_policy_version,
)
from ugc_bot.infrastructure.db.repositories.work_entitlements import (
    SqlAlchemyWorkEntitlementRepository,
)
from ugc_bot.infrastructure.db.selection_maturity_models import TABLES


async def rows(db, name, **scope):
    return (
        (
            await db.execute(
                select(Base.metadata.tables[name]).filter_by(**scope)
            )
        )
        .mappings()
        .all()
    )


class SqlAlchemySelectionMaturityRepository:
    async def load(self, order_id, *, session):
        db = _session(session)
        orders = await rows(db, "orders", order_id=order_id)
        if not orders or not orders[0]["financial_version"]:
            raise ValueError("selection_financial_order_required")
        order = orders[0]
        policy = await db.get(
            FinancialPolicyVersionModel, order["financial_version"]
        )
        if policy is None:
            raise ValueError("approved_policy_required")
        approved = decode_policy_version(policy)
        events = await rows(
            db,
            "outbox_events",
            aggregate_id=str(order_id),
            event_type="financial.client_snapshot_requested",
        )
        if len(events) != 1:
            raise ValueError("selection_capture_source_required")
        payment_id = UUID(events[0]["payload"]["payment_id"])
        payments = await rows(db, "payments", payment_id=payment_id)
        items = sorted(
            await rows(db, "order_items", order_id=order_id),
            key=lambda i: i["ordinal"],
        )
        if len(payments) != 1 or not items:
            raise ValueError("selection_capture_source_required")
        payment = payments[0]
        if (
            payment["order_id"] != order_id
            or payment["captured_minor"]
            != sum(
                i["selection_minor"] + i["accompaniment_minor"] for i in items
            )
            or payment["paid_at"] is None
        ):
            raise ValueError("selection_capture_scope_mismatch")
        positions = []
        for item in items:
            if (
                item["policy_version"] != approved.version
                or item["captured_at"] != payment["paid_at"]
                or item["quote_payload"].get("terms_reference")
                != approved.terms_reference
            ):
                raise ValueError("selection_item_scope_mismatch")
            deliveries = await rows(
                db,
                "paid_selection_accepted_deliveries",
                paid_item_id=item["paid_item_id"],
            )
            delivered = deliveries[0] if deliveries else None
            if delivered is not None and (
                delivered["order_id"] != order_id
                or delivered["payment_id"] != payment_id
                or delivered["client_id"] != order["advertiser_id"]
            ):
                raise ValueError("selection_delivery_scope_mismatch")
            refunds = await rows(
                db,
                "financial_refund_component_applications",
                paid_item_id=item["paid_item_id"],
            )
            refunded_at, application = await self._refund_resolution(
                db, item, refunds, payment_id
            )
            positions.append(
                SelectionPosition(
                    item["paid_item_id"],
                    delivered["accepted_at"] if delivered else None,
                    delivered["delivery_id"] if delivered else None,
                    refunded_at,
                    application,
                )
            )
        return SelectionSnapshot(
            order_id,
            order["advertiser_id"],
            payment_id,
            approved,
            payment["paid_at"],
            tuple(positions),
        )

    @staticmethod
    async def _refund_resolution(db, item, refunds, payment_id):
        if not refunds:
            return None, None
        if sum(r["refund_minor"] for r in refunds) != item[
            "selection_minor"
        ] or any(
            r["component"] != "selection" or r["payment_id"] != payment_id
            for r in refunds
        ):
            raise ValueError("selection_refund_scope_mismatch")
        apps = [
            await rows(
                db,
                "financial_refund_applications",
                application_id=r["application_id"],
            )
            for r in refunds
        ]
        if any(len(a) != 1 for a in apps):
            raise ValueError("selection_refund_source_required")
        latest = max((a[0] for a in apps), key=lambda a: a["recorded_at"])
        return latest["recorded_at"], latest["application_id"]

    async def lock_order(self, order_id, *, session):
        await SqlAlchemyFinancialItemRepository().lock_order(
            order_id, session=session
        )

    async def load_actor(self, actor_id, *, session):
        return await SqlAlchemyCollaborationRepository().load_actor(
            actor_id, session=session
        )

    async def get_closure(self, order_id, *, session):
        row = (
            (
                await _session(session).execute(
                    select(TABLES["closures"]).where(
                        TABLES["closures"].c.order_id == order_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return SelectionClosure(**row) if row else None

    async def save_closure(self, closure, *, session):
        await _session(session).execute(
            insert(TABLES["closures"]).values(**asdict(closure))
        )
        return closure

    async def save_schedule(self, schedule, *, session):
        table = TABLES["schedules"]
        db = _session(session)
        await db.execute(
            insert(table)
            .values(**asdict(schedule))
            .on_conflict_do_nothing(index_elements=["paid_item_id"])
        )
        actual = (
            (
                await db.execute(
                    select(table).where(
                        table.c.paid_item_id == schedule.paid_item_id
                    )
                )
            )
            .mappings()
            .one()
        )
        result = SelectionMaturitySource(**actual)
        if result != schedule:
            raise ValueError("selection_schedule_conflict")
        return result

    async def require_clear(self, item_id, *, session):
        if (
            await SqlAlchemyWorkEntitlementRepository().get_dispute_case(
                item_id, session=session
            )
            is not None
        ):
            raise ValueError("work_disputed")
        await LiveCorrectionFundingGuard(
            SqlAlchemyCorrectionRepository()
        ).require_forward_clear(
            item_id, session=session, components=("selection",)
        )

    async def list_orders(self, *, after=None, limit=100, session):
        table = Base.metadata.tables["order_items"]
        statement = select(table.c.order_id).where(
            table.c.captured_at.is_not(None)
        )
        if after is not None:
            statement = statement.where(table.c.order_id > after)
        return tuple(
            (
                await _session(session).scalars(
                    statement.distinct().order_by(table.c.order_id).limit(limit)
                )
            ).all()
        )
