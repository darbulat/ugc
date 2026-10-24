"""Actual lifecycle and captured funding, never money from an outbox payload."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.application.collaboration_ports import (
    CollaborationScope,
    record_from_payload,
)
from ugc_bot.application.work_entitlement_ports import (
    WORK_EVENT_TYPES,
    WorkDisputeCase,
    WorkEntitlementSnapshot,
)
from ugc_bot.infrastructure.db.collaboration_models import (
    CollaborationEventModel,
    CollaborationModel,
    CollaborationReleaseScheduleModel,
)
from ugc_bot.infrastructure.db.models import ManagerOrderModel, OutboxEventModel
from ugc_bot.infrastructure.db.repositories.entitlements import (
    SqlAlchemyClientEntitlementRepository,
    _require,
    _row,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    _canonical,
    payload_hash,
)
from ugc_bot.infrastructure.db.repositories.outbox import (
    _to_outbox_event_entity,
)
from ugc_bot.infrastructure.db.work_entitlement_models import WORK_ASSESSMENTS


async def _work_source(db, event):
    source = await _row(db, "outbox_events", "event_id", event.event_id)
    fact = await _row(
        db, "financial_collaboration_events", "event_id", event.event_id
    )
    _require(
        event.event_type in WORK_EVENT_TYPES
        and source["event_type"] == fact["event_type"] == event.event_type
        and source["aggregate_type"] == event.aggregate_type == "collaboration"
        and source["aggregate_id"]
        == event.aggregate_id
        == str(fact["assignment_id"])
        and source["payload"]
        == event.payload
        == {"collaboration_event_id": str(fact["event_id"])},
        "work_source_mismatch",
    )
    proof = record_from_payload(fact["result_payload"])
    _require(
        proof.collaboration.assignment_id == fact["assignment_id"]
        and proof.version == fact["version"]
        and proof.updated_at == fact["occurred_at"],
        "work_event_scope_mismatch",
    )
    return source, fact


def _digest(source, fact):
    return payload_hash(
        dict(
            source={
                key: source[key]
                for key in (
                    "event_id",
                    "event_type",
                    "aggregate_id",
                    "aggregate_type",
                    "payload",
                )
            },
            fact=dict(fact),
        )
    )


class SqlAlchemyWorkEntitlementRepository:
    def __init__(self, funding_repository=None):
        self.funding = (
            funding_repository or SqlAlchemyClientEntitlementRepository()
        )

    async def source_hash(self, event, *, session):
        source, fact = await _work_source(_session(session), event)
        return _digest(source, fact)

    async def load(self, event, *, session):
        db = _session(session)
        source, fact = await _work_source(db, event)
        assignment = await _row(
            db, "item_assignments", "assignment_id", fact["assignment_id"]
        )
        row = await _row(
            db,
            "financial_collaborations",
            "assignment_id",
            assignment["assignment_id"],
        )
        record = record_from_payload(row["record_payload"])
        current = (
            (
                await db.execute(
                    select(CollaborationEventModel.__table__).where(
                        CollaborationEventModel.assignment_id
                        == assignment["assignment_id"],
                        CollaborationEventModel.version == row["version"],
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        _require(
            current is not None
            and current["result_payload"] == row["record_payload"]
            and record.version == row["version"]
            and record.collaboration.state == row["state"]
            and record.paid_item_id == assignment["paid_item_id"]
            and record.collaboration.assignment_id
            == assignment["assignment_id"],
            "work_current_fact_mismatch",
        )
        outbox = await db.scalar(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_type == "order",
                OutboxEventModel.aggregate_id == str(row["order_id"]),
                OutboxEventModel.event_type
                == "financial.client_snapshot_requested",
            )
        )
        _require(outbox is not None, "work_capture_source_missing")
        assert outbox is not None and current is not None
        capture = await self.funding.load_capture(
            _to_outbox_event_entity(outbox), session=db
        )
        scope = CollaborationScope(
            assignment_id=assignment["assignment_id"],
            paid_item_id=assignment["paid_item_id"],
            order_id=capture.order_id,
            client_id=capture.client_id,
            creator_id=assignment["creator_id"],
            manager_id=assignment["manager_id"],
            policy_version=capture.policy.version,
            captured_at=capture.captured_at,
            valid_from=assignment["valid_from"],
            valid_to=assignment["valid_to"],
            selection_funded=any(
                item.paid_item_id == assignment["paid_item_id"]
                and item.selection_minor == 50000
                for item in capture.items
            ),
        )
        schedule = (
            (
                await db.execute(
                    select(CollaborationReleaseScheduleModel.__table__).where(
                        CollaborationReleaseScheduleModel.assignment_id
                        == scope.assignment_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        manager_linked = await self._manager_proof(db, scope, record, schedule)
        return WorkEntitlementSnapshot(
            scope,
            record,
            capture,
            _digest(source, fact),
            manager_linked,
            schedule["schedule_id"] if schedule else None,
            current["event_id"],
        )

    @staticmethod
    async def _manager_proof(db, scope, record, schedule):
        if scope.manager_id is None:
            return False
        if schedule is not None:
            assessments = (
                (
                    await db.execute(
                        select(WORK_ASSESSMENTS.c.assessment).where(
                            WORK_ASSESSMENTS.c.assignment_id
                            == scope.assignment_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if any(
                a.get("manager") == "successful_funded_management"
                and a.get("manager_id") == str(scope.manager_id)
                and a.get("management_schedule_id")
                == str(schedule["schedule_id"])
                for a in assessments
            ):
                return True
        manager = await db.scalar(
            select(ManagerOrderModel.created_at).where(
                ManagerOrderModel.order_id == scope.order_id,
                ManagerOrderModel.user_id == scope.manager_id,
            )
        )
        success = record.collaboration.success_final_at
        return manager is not None and (success is None or manager <= success)

    async def lock_funding(self, snapshot, *, session):
        db = _session(session)
        await self.funding.lock_funding(snapshot.capture, session=db)
        if snapshot.scope.manager_id is not None:
            # Order barrier comes first, so a cascading order deletion cannot
            # invert this association lock with the producer's order lock.
            await db.execute(
                select(ManagerOrderModel.user_id)
                .where(
                    ManagerOrderModel.order_id == snapshot.scope.order_id,
                    ManagerOrderModel.user_id == snapshot.scope.manager_id,
                )
                .with_for_update(read=True, key_share=True)
            )

    async def get_receipt(self, event_id, *, session):
        return (
            (
                await _session(session).execute(
                    select(WORK_ASSESSMENTS).where(
                        WORK_ASSESSMENTS.c.event_id == event_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def save_receipt(
        self, event, snapshot, assessment, *, recorded_at, session
    ):
        db = _session(session)
        values = dict(
            event_id=event.event_id,
            assignment_id=snapshot.scope.assignment_id,
            paid_item_id=snapshot.scope.paid_item_id,
            order_id=snapshot.scope.order_id,
            payment_id=snapshot.capture.payment_id,
            source_hash=snapshot.source_hash,
            assessment=_canonical(assessment),
            recorded_at=recorded_at,
        )
        await db.execute(
            insert(WORK_ASSESSMENTS)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[WORK_ASSESSMENTS.c.event_id]
            )
        )
        stored = await self.get_receipt(event.event_id, session=db)
        if stored["source_hash"] != snapshot.source_hash:
            raise ValueError("idempotency_payload_conflict")

    async def get_dispute_case(self, paid_item_id, *, session):
        db = _session(session)
        rows = (
            (
                await db.execute(
                    select(CollaborationModel.__table__)
                    .where(
                        CollaborationModel.paid_item_id == paid_item_id,
                        CollaborationModel.state == "disputed",
                    )
                    .order_by(
                        CollaborationModel.updated_at,
                        CollaborationModel.assignment_id,
                    )
                )
            )
            .mappings()
            .all()
        )
        cases = []
        for row in rows:
            fact = (
                (
                    await db.execute(
                        select(CollaborationEventModel.__table__).where(
                            CollaborationEventModel.assignment_id
                            == row["assignment_id"],
                            CollaborationEventModel.version == row["version"],
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            cases.append(self._dispute_case(row, fact))
        return cases[0] if cases else None

    @staticmethod
    def _dispute_case(row, fact):
        _require(fact is not None, "work_dispute_source_missing")
        proof = record_from_payload(fact["result_payload"])
        work = proof.collaboration
        expected = uuid5(
            NAMESPACE_URL, f"ugc:collaboration-case:{fact['event_id']}"
        )
        _require(
            fact["event_type"] == "financial.collaboration.disputed"
            and fact["result_payload"] == row["record_payload"]
            and fact["assignment_id"]
            == work.assignment_id
            == row["assignment_id"]
            and proof.paid_item_id == row["paid_item_id"]
            and proof.order_id == row["order_id"]
            and work.state == "disputed"
            and fact["actor_id"] in (work.client_id, work.creator_id)
            and fact["actor_id"] != work.claimant_id
            and fact["system_actor"] is None
            and isinstance(work.dispute_reason, str)
            and bool(work.dispute_reason.strip())
            and fact["parameters"].get("case_id") == str(expected)
            and isinstance(fact["parameters"].get("reason"), str)
            and fact["parameters"]["reason"].strip() == work.dispute_reason
            and fact["parameters"].get("actor_id") == str(fact["actor_id"]),
            "work_dispute_source_mismatch",
        )
        assert isinstance(work.dispute_reason, str)
        return WorkDisputeCase(
            expected,
            work.assignment_id,
            proof.paid_item_id,
            fact["event_id"],
            fact["actor_id"],
            work.dispute_reason,
            fact["occurred_at"],
        )
