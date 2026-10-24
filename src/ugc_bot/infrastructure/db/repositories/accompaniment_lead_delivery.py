"""Dedicated notification owner; no User FK lock after delivery-job locks."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.application.accompaniment_lead_ports import (
    LeadAttempt,
    LeadDeliveryJob,
    LeadOutcome,
)
from ugc_bot.application.notice_delivery_ports import DeliveryContact
from ugc_bot.domain.order_intake import AccompanimentLead
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.order_intake_models import (
    ACCOMPANIMENT_LEADS,
    LEAD_ATTEMPTS,
    LEAD_DELIVERIES,
    LEAD_OUTBOX,
    LEAD_OUTCOMES,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyAccompanimentLeadDeliveryRepository:
    async def expand(
        self, at: datetime, limit: int, *, session: object
    ) -> None:
        db = _session(session)
        pending = (
            (
                await db.execute(
                    select(LEAD_OUTBOX)
                    .where(
                        LEAD_OUTBOX.c.expanded_at.is_(None),
                    )
                    .order_by(LEAD_OUTBOX.c.created_at, LEAD_OUTBOX.c.lead_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .all()
        )
        admins = (
            await db.scalars(
                select(UserModel.user_id)
                .where(
                    UserModel.admin.is_(True),
                    UserModel.status == "active",
                )
                .order_by(UserModel.user_id)
            )
        ).all()
        if not admins:
            return
        for source in pending:
            # Revalidate source before expanding the server-owned audience.
            await self.lead(source["lead_id"], session=db)
            for admin in admins:
                await db.execute(
                    insert(LEAD_DELIVERIES)
                    .values(
                        **asdict(
                            LeadDeliveryJob(
                                uuid5(source["lead_id"], str(admin)),
                                source["lead_id"],
                                source["order_id"],
                                admin,
                            )
                        )
                    )
                    .on_conflict_do_nothing(
                        index_elements=["lead_id", "recipient_id"]
                    )
                )
            await db.execute(
                update(LEAD_OUTBOX)
                .where(
                    LEAD_OUTBOX.c.lead_id == source["lead_id"],
                )
                .values(expanded_at=at)
            )

    async def candidates(
        self, at: datetime, limit: int, *, session: object
    ) -> tuple[UUID, ...]:
        return tuple(
            (
                await _session(session).scalars(
                    select(LEAD_DELIVERIES.c.job_id)
                    .where(
                        or_(
                            LEAD_DELIVERIES.c.state == "ready",
                            and_(
                                LEAD_DELIVERIES.c.state == "sending",
                                LEAD_DELIVERIES.c.lease_until <= at,
                            ),
                        )
                    )
                    .order_by(LEAD_DELIVERIES.c.job_id)
                    .limit(limit)
                )
            ).all()
        )

    async def lock_job(
        self, job_id: UUID, *, session: object
    ) -> LeadDeliveryJob | None:
        row = (
            (
                await _session(session).execute(
                    select(LEAD_DELIVERIES)
                    .where(
                        LEAD_DELIVERIES.c.job_id == job_id,
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        return LeadDeliveryJob(**row) if row is not None else None

    async def lead(
        self, lead_id: UUID, *, session: object
    ) -> AccompanimentLead:
        row = (
            (
                await _session(session).execute(
                    select(ACCOMPANIMENT_LEADS).where(
                        ACCOMPANIMENT_LEADS.c.lead_id == lead_id,
                    )
                )
            )
            .mappings()
            .one()
        )
        return AccompanimentLead(
            row["lead_id"],
            row["request_id"],
            row["order_id"],
            row["client_id"],
            row["requested_at"],
            row["contact_reference"],
            tuple(row["selected_ordinals"]),
        )

    async def contact(
        self, user_id: UUID, *, session: object
    ) -> DeliveryContact | None:
        user = await _session(session).get(
            UserModel, user_id, populate_existing=True
        )
        if user is None or not user.admin or user.status != "active":
            return None
        channel: str
        address: str | None
        kind: str
        if user.telegram_id:
            channel, address, kind = "telegram", user.telegram_id, "chat_id"
        else:
            channel, address, kind = (
                "max",
                user.max_chat_id or user.max_id,
                "chat_id" if user.max_chat_id else "user_id",
            )
        return DeliveryContact(
            user_id, channel, address, user.language or "ru", user.status, kind
        )

    async def is_admin(self, user_id: UUID, *, session: object) -> bool:
        user = await _session(session).get(
            UserModel, user_id, populate_existing=True
        )
        return bool(user is not None and user.admin and user.status == "active")

    async def save_job(self, job: LeadDeliveryJob, *, session: object) -> None:
        data = asdict(job)
        for name in ("job_id", "lead_id", "order_id", "recipient_id"):
            data.pop(name)
        await _session(session).execute(
            update(LEAD_DELIVERIES)
            .where(
                LEAD_DELIVERIES.c.job_id == job.job_id,
            )
            .values(**data)
        )

    async def save_attempt(
        self, attempt: LeadAttempt, *, session: object
    ) -> None:
        await _session(session).execute(
            insert(LEAD_ATTEMPTS).values(**asdict(attempt))
        )

    async def get_attempt(
        self, attempt_id: UUID, *, session: object
    ) -> LeadAttempt:
        row = (
            (
                await _session(session).execute(
                    select(LEAD_ATTEMPTS).where(
                        LEAD_ATTEMPTS.c.attempt_id == attempt_id,
                    )
                )
            )
            .mappings()
            .one()
        )
        return LeadAttempt(**row)

    async def save_outcome(
        self, outcome: LeadOutcome, *, session: object
    ) -> None:
        db = _session(session)
        inserted = await db.scalar(
            insert(LEAD_OUTCOMES)
            .values(
                **asdict(outcome),
            )
            .on_conflict_do_nothing(index_elements=["attempt_id", "kind"])
            .returning(LEAD_OUTCOMES.c.outcome_id)
        )
        if inserted is not None:
            return
        previous = (
            (
                await db.execute(
                    select(LEAD_OUTCOMES).where(
                        LEAD_OUTCOMES.c.attempt_id == outcome.attempt_id,
                        LEAD_OUTCOMES.c.kind == outcome.kind,
                    )
                )
            )
            .mappings()
            .one()
        )
        # recorded_at/applied describe the first processing of the proof;
        # replay cannot rewrite them, and a late receipt cannot alter recovery.
        facts = (
            "attempt_id",
            "job_id",
            "lead_id",
            "order_id",
            "kind",
            "status",
            "provider_reference",
            "reason",
            "actor_id",
            "operation_key",
            "payload_hash",
        )
        if any(previous[name] != getattr(outcome, name) for name in facts):
            raise ValueError("lead_outcome_payload_conflict")

    async def command_outcome(
        self, operation_key: str, *, session: object
    ) -> LeadOutcome | None:
        row = (
            (
                await _session(session).execute(
                    select(LEAD_OUTCOMES).where(
                        LEAD_OUTCOMES.c.operation_key == operation_key,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return LeadOutcome(**row) if row is not None else None
