"""Actual captured item, current work and immutable manual bank reports."""

from datetime import datetime, timezone

from sqlalchemy import insert, select

from ugc_bot.application.accompaniment_refund_ports import (
    AccompanimentRefundScope,
)
from ugc_bot.application.collaboration_ports import record_from_payload
from ugc_bot.infrastructure.db.accompaniment_refund_models import TABLES
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import OutboxEventModel
from ugc_bot.infrastructure.db.repositories.corrections import (
    SqlAlchemyCorrectionRepository,
)
from ugc_bot.infrastructure.db.repositories.entitlements import _require, _row
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.outbox import (
    _to_outbox_event_entity,
)
from ugc_bot.infrastructure.db.repositories.selection_delivery_funding import (
    SqlAlchemySelectionFundingRepository,
)


class SqlAlchemyAccompanimentRefundRepository:
    async def load_scope(self, paid_item_id, *, session):
        db = _session(session)
        item = await _row(db, "order_items", "paid_item_id", paid_item_id)
        capture_event = (
            await db.scalars(
                select(OutboxEventModel).where(
                    OutboxEventModel.aggregate_type == "order",
                    OutboxEventModel.aggregate_id == str(item["order_id"]),
                    OutboxEventModel.event_type
                    == "financial.client_snapshot_requested",
                )
            )
        ).one()
        capture = await SqlAlchemySelectionFundingRepository().load_capture(
            _to_outbox_event_entity(capture_event), session=db
        )
        record = await self._work_record(paid_item_id, session=db)
        _require(
            record is None
            or (
                record.order_id == capture.order_id
                and record.collaboration.client_id == capture.client_id
                and record.policy_version == capture.policy.version
            ),
            "accompaniment_capture_scope_mismatch",
        )
        payment = await _row(db, "payments", "payment_id", capture.payment_id)
        work = record.collaboration if record else None
        earned = False
        if (
            work is not None
            and work.manager_id is not None
            and work.state
            in (
                "success_final",
                "available",
            )
        ):
            managers = Base.metadata.tables["manager_orders"]
            since = await db.scalar(
                select(managers.c.created_at).where(
                    managers.c.order_id == capture.order_id,
                    managers.c.user_id == work.manager_id,
                )
            )
            earned = since is not None and since <= work.success_final_at
        return AccompanimentRefundScope(
            capture, record, payment["external_id"], earned, paid_item_id
        )

    async def _work_record(self, paid_item_id, *, session):
        db = _session(session)
        assignment = Base.metadata.tables["item_assignments"]
        assignments = (
            (
                await db.execute(
                    select(assignment).where(
                        assignment.c.paid_item_id == paid_item_id,
                        assignment.c.valid_to.is_(None),
                    )
                )
            )
            .mappings()
            .all()
        )
        _require(len(assignments) <= 1, "accompaniment_current_work_required")
        if not assignments:
            return None
        current = Base.metadata.tables["financial_collaborations"]
        row = (
            (
                await db.execute(
                    select(current).where(
                        current.c.assignment_id
                        == assignments[0]["assignment_id"]
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        record = record_from_payload(row["record_payload"])
        events = Base.metadata.tables["financial_collaboration_events"]
        fact = (
            (
                await db.execute(
                    select(events).where(
                        events.c.assignment_id == row["assignment_id"],
                        events.c.version == row["version"],
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        _require(
            fact is not None
            and fact["result_payload"] == row["record_payload"]
            and record.version == row["version"]
            and record.collaboration.state == row["state"]
            and record.paid_item_id == paid_item_id,
            "work_current_fact_mismatch",
        )
        return record

    async def lock_scope(self, scope, *, session):
        await SqlAlchemySelectionFundingRepository().lock_funding(
            scope.capture, session=session
        )

    async def load_actor(self, actor_id, *, session):
        return await SqlAlchemyCorrectionRepository().actor(
            actor_id, session=session
        )

    async def get_command(self, actor_id, key, *, session):
        row = (
            (
                await _session(session).execute(
                    select(TABLES["commands"]).where(
                        TABLES["commands"].c.actor_id == actor_id,
                        TABLES["commands"].c.operation_key == key,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return (row["payload_hash"], row["result"]) if row else None

    async def save_command(self, actor_id, key, digest, result, *, session):
        await _session(session).execute(
            insert(TABLES["commands"]).values(
                actor_id=actor_id,
                operation_key=key,
                payload_hash=digest,
                result=result,
                recorded_at=datetime.now(timezone.utc),
            )
        )

    async def observation(self, identity, *, session):
        return (
            (
                await _session(session).execute(
                    select(TABLES["observations"]).where(
                        TABLES["observations"].c.observation_id == identity
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def append_observation(self, fact, *, session):
        await _session(session).execute(
            insert(TABLES["observations"]).values(**fact)
        )

    async def totals(self, item_id, *, session):
        rows = (
            (
                await _session(session).execute(
                    select(TABLES["applications"]).where(
                        TABLES["applications"].c.paid_item_id == item_id
                    )
                )
            )
            .mappings()
            .all()
        )
        return sum(r["customer_delta_minor"] for r in rows), sum(
            r["manager_delta_minor"] for r in rows
        )

    async def application(self, identity, *, session):
        return (
            (
                await _session(session).execute(
                    select(TABLES["applications"]).where(
                        TABLES["applications"].c.observation_id == identity
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def append_application(self, fact, *, session):
        await _session(session).execute(
            insert(TABLES["applications"]).values(**fact)
        )

    async def latest_application(self, item_id, *, session):
        table = TABLES["applications"]
        return (
            (
                await _session(session).execute(
                    select(table)
                    .where(table.c.paid_item_id == item_id)
                    .order_by(table.c.customer_target_minor.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )

    async def append_management_review(self, fact, *, session):
        await _session(session).execute(
            insert(TABLES["management_reviews"]).values(**fact)
        )
