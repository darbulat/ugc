"""Exact notice-event ownership, immutable attempt/outcome facts; no commits."""

from dataclasses import asdict

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ugc_bot.application.collaboration_ports import (
    CollaborationEvent,
    CollaborationNotice,
    record_from_payload,
)
from ugc_bot.application.notice_delivery_ports import (
    NOTICE_EVENT_TYPE,
    DeliveryContact,
    DeliveryJob,
    NoticeAttempt,
    NoticeOrigin,
    NoticeOutcome,
)
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.db.collaboration_models import (
    CollaborationEventModel,
    CollaborationNoticeModel,
)
from ugc_bot.infrastructure.db.models import OutboxEventModel, UserModel
from ugc_bot.infrastructure.db.notice_delivery_models import (
    NoticeDeliveryAttemptModel,
    NoticeDeliveryJobModel,
    NoticeDeliveryOutcomeModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyNoticeDeliveryRepository:
    async def candidates(self, at, limit, *, session):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("notice_batch_limit_invalid")
        event, job = (
            OutboxEventModel.__table__,
            NoticeDeliveryJobModel.__table__,
        )
        result = await _session(session).scalars(
            select(event.c.event_id)
            .outerjoin(job, job.c.event_id == event.c.event_id)
            .where(
                event.c.event_type == NOTICE_EVENT_TYPE,
                or_(
                    event.c.status == OutboxEventStatus.PENDING,
                    and_(
                        event.c.status == OutboxEventStatus.PROCESSING,
                        job.c.state.in_(("prepared", "sending")),
                        job.c.lease_until <= at,
                    ),
                ),
            )
            .order_by(event.c.created_at, event.c.event_id)
            .limit(limit)
        )
        return tuple(result)

    async def origin(self, event_id, *, session):
        db = _session(session)
        event = (
            (
                await db.execute(
                    select(OutboxEventModel.__table__).where(
                        OutboxEventModel.event_id == event_id,
                        OutboxEventModel.event_type == NOTICE_EVENT_TYPE,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if event is None:
            return None
        notice = (
            (
                await db.execute(
                    select(CollaborationNoticeModel.__table__).where(
                        CollaborationNoticeModel.notice_id == event_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        source = None
        if notice:
            row = (
                (
                    await db.execute(
                        select(CollaborationEventModel.__table__).where(
                            CollaborationEventModel.event_id
                            == notice["source_event_id"]
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row:
                source = CollaborationEvent(
                    row["event_id"],
                    row["assignment_id"],
                    row["operation_key"],
                    row["payload_hash"],
                    row["event_type"],
                    row["actor_id"],
                    row["system_actor"],
                    row["parameters"],
                    record_from_payload(row["result_payload"]),
                    row["occurred_at"],
                )
        fields = OutboxEvent.__dataclass_fields__
        return NoticeOrigin(
            OutboxEvent(**{key: event[key] for key in fields}),
            CollaborationNotice(**notice) if notice else None,
            source,
        )

    async def contact(self, recipient_id, *, session):
        # Nonlocking core SELECT after item lock: never take a User/Wallet lock.
        user = (
            (
                await _session(session).execute(
                    select(UserModel.__table__).where(
                        UserModel.user_id == recipient_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if user is None:
            return None
        channel = str(user["messenger_type"])
        address, kind = (
            (user["telegram_id"], "chat_id")
            if channel == "telegram"
            else (
                user["max_chat_id"] or user["max_id"],
                "chat_id" if user["max_chat_id"] else "user_id",
            )
            if channel == "max"
            else (None, "chat_id")
        )
        return DeliveryContact(
            recipient_id,
            channel,
            str(address) if address is not None else None,
            user["language"] or "ru",
            str(user["status"]),
            kind,
        )

    async def lock_job(self, origin, *, session):
        db = _session(session)
        await db.execute(
            pg_insert(NoticeDeliveryJobModel)
            .values(
                **asdict(
                    DeliveryJob(origin.event.event_id, origin.notice.notice_id)
                )
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        row = (
            (
                await db.execute(
                    select(NoticeDeliveryJobModel.__table__)
                    .where(
                        NoticeDeliveryJobModel.event_id == origin.event.event_id
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one()
        )
        return DeliveryJob(**row)

    async def save_job(self, job, *, session):
        values = asdict(job)
        values.pop("event_id")
        result = await _session(session).execute(
            update(NoticeDeliveryJobModel)
            .where(NoticeDeliveryJobModel.event_id == job.event_id)
            .values(**values)
        )
        if result.rowcount != 1:
            raise ValueError("notice_job_not_found")

    async def save_attempt(self, attempt, *, session):
        await _session(session).execute(
            insert(NoticeDeliveryAttemptModel).values(**asdict(attempt))
        )

    async def get_attempt(self, attempt_id, *, session):
        row = (
            (
                await _session(session).execute(
                    select(NoticeDeliveryAttemptModel.__table__).where(
                        NoticeDeliveryAttemptModel.attempt_id == attempt_id
                    )
                )
            )
            .mappings()
            .one()
        )
        return NoticeAttempt(**row)

    async def list_outcomes(self, attempt_id, *, session):
        rows = (
            await _session(session).execute(
                select(NoticeDeliveryOutcomeModel.__table__)
                .where(NoticeDeliveryOutcomeModel.attempt_id == attempt_id)
                .order_by(
                    NoticeDeliveryOutcomeModel.recorded_at,
                    NoticeDeliveryOutcomeModel.outcome_id,
                )
            )
        ).mappings()
        return tuple(NoticeOutcome(**row) for row in rows)

    async def retry_outcome(self, operation_key, *, session):
        row = (
            (
                await _session(session).execute(
                    select(NoticeDeliveryOutcomeModel.__table__).where(
                        NoticeDeliveryOutcomeModel.kind == "retry",
                        NoticeDeliveryOutcomeModel.operation_key
                        == operation_key,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return NoticeOutcome(**row) if row else None

    async def save_outcome(self, outcome, *, session):
        await _session(session).execute(
            insert(NoticeDeliveryOutcomeModel).values(**asdict(outcome))
        )

    async def settle_event(self, event_id, state, at, reason=None, *, session):
        status = {
            "ready": OutboxEventStatus.PENDING,
            "prepared": OutboxEventStatus.PROCESSING,
            "sending": OutboxEventStatus.PROCESSING,
            "complete": OutboxEventStatus.PUBLISHED,
            "obsolete": OutboxEventStatus.PUBLISHED,
            "failed": OutboxEventStatus.FAILED,
            "unknown": OutboxEventStatus.FAILED,
        }[state]
        values = dict(
            status=status,
            processed_at=at
            if status in (OutboxEventStatus.PUBLISHED, OutboxEventStatus.FAILED)
            else None,
            last_error=reason,
            claimed_at=at if state in ("prepared", "sending") else None,
        )
        result = await _session(session).execute(
            update(OutboxEventModel)
            .where(
                OutboxEventModel.event_id == event_id,
                OutboxEventModel.event_type == NOTICE_EVENT_TYPE,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise ValueError("notice_event_owner_required")
