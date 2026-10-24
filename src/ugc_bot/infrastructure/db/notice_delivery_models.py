"""Mutable leases, immutable attempts and provider outcomes."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ugc_bot.infrastructure.db.base import Base


class NoticeDeliveryJobModel(Base):
    __tablename__ = "financial_notice_jobs"
    __table_args__ = (
        sa.CheckConstraint(
            "event_id = notice_id", name="ck_notice_job_identity"
        ),
        sa.CheckConstraint(
            "state IN "
            "('ready','prepared','sending','complete','failed','unknown','obsolete')",
            name="ck_notice_job_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_notice_job_count"),
        sa.CheckConstraint(
            "state NOT IN ('prepared','sending') OR (current_attempt_id IS "
            "NOT NULL AND lease_token IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_notice_job_lease",
        ),
        sa.Index("ix_notice_job_lease", "state", "lease_until"),
    )
    event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("outbox_events.event_id"),
        primary_key=True,
    )
    notice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("financial_collaboration_notices.notice_id"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    attempt_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    current_attempt_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True)
    )
    lease_token: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )


class NoticeDeliveryAttemptModel(Base):
    __tablename__ = "financial_notice_attempts"
    __table_args__ = (
        sa.UniqueConstraint(
            "event_id", "number", name="uq_notice_attempt_number"
        ),
        sa.CheckConstraint(
            "event_id = notice_id AND number > 0 AND collaboration_version > "
            "0 AND lease_until > prepared_at",
            name="ck_notice_attempt_provenance",
        ),
        sa.CheckConstraint(
            "channel IS NULL OR channel IN ('telegram','max','whatsapp')",
            name="ck_notice_attempt_channel",
        ),
        sa.CheckConstraint(
            "address_kind IN ('chat_id','user_id')",
            name="ck_notice_attempt_address_kind",
        ),
        sa.CheckConstraint(
            "(action_url IS NULL AND action_label IS NULL) OR "
            "(action_url IS NOT NULL AND action_label IS NOT NULL AND "
            "length(trim(action_url)) > 0 AND length(trim(action_label)) > 0)",
            name="ck_notice_attempt_action_pair",
        ),
    )
    attempt_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("financial_notice_jobs.event_id"),
        nullable=False,
    )
    notice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("financial_collaboration_notices.notice_id"),
        nullable=False,
    )
    assignment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("financial_collaborations.assignment_id"),
        nullable=False,
    )
    source_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("financial_collaboration_events.event_id"),
        nullable=False,
    )
    # The immutable notice/proof trigger fixes this UUID. A direct User FK
    # would take KEY SHARE after the item lock and invert the money lock order.
    recipient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    lease_token: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    prepared_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    lease_until: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    collaboration_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    channel: Mapped[str | None] = mapped_column(sa.String(30))
    address: Mapped[str | None] = mapped_column(sa.Text)
    address_kind: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    locale: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    deadline: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    action_url: Mapped[str | None] = mapped_column(sa.Text)
    action_label: Mapped[str | None] = mapped_column(sa.Text)


class NoticeDeliveryOutcomeModel(Base):
    __tablename__ = "financial_notice_outcomes"
    __table_args__ = (
        sa.UniqueConstraint(
            "attempt_id", "kind", name="uq_notice_attempt_observation"
        ),
        sa.UniqueConstraint("operation_key", name="uq_notice_retry_operation"),
        sa.CheckConstraint(
            "kind IN "
            "('transport','recovery','retry','retry_guard','context_guard')",
            name="ck_notice_outcome_kind",
        ),
        sa.CheckConstraint(
            "status IN ('accepted','failed','unknown','obsolete','authorized')",
            name="ck_notice_outcome_status",
        ),
        sa.CheckConstraint(
            "status <> 'accepted' OR length(trim(provider_reference)) > 0 "
            "AND provider_reference IS NOT NULL",
            name="ck_notice_outcome_receipt",
        ),
        sa.CheckConstraint(
            "(kind = 'retry' AND status = 'authorized' AND actor_id IS NOT "
            "NULL AND operation_key IS NOT NULL AND length(trim(reason)) > "
            "0) OR (kind <> 'retry' AND actor_id IS NULL AND operation_key "
            "IS NULL)",
            name="ck_notice_retry_audit",
        ),
    )
    outcome_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    attempt_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("financial_notice_attempts.attempt_id"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    provider_reference: Mapped[str | None] = mapped_column(sa.Text)
    reason: Mapped[str | None] = mapped_column(sa.Text)
    applied: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    # Current admin authorization is checked by the service and retained here;
    # do not acquire an implicit User KEY SHARE while holding the item lock.
    actor_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    operation_key: Mapped[str | None] = mapped_column(sa.String(250))


MODELS = (
    NoticeDeliveryJobModel,
    NoticeDeliveryAttemptModel,
    NoticeDeliveryOutcomeModel,
)
TABLES: tuple[sa.Table, ...] = tuple(
    Base.metadata.tables[model.__tablename__] for model in MODELS
)
DENY_MUTATION = """
CREATE OR REPLACE FUNCTION notice_deny_fact_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'notice_fact_immutable' USING ERRCODE='23514';
END $$;
"""
ATTEMPT_PROOF = """
CREATE OR REPLACE FUNCTION notice_check_attempt_proof() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM financial_collaboration_notices n
   JOIN outbox_events e ON e.event_id=n.notice_id
   WHERE n.notice_id=NEW.notice_id AND n.assignment_id=NEW.assignment_id
   AND n.source_event_id=NEW.source_event_id AND n.recipient_id=NEW.recipient_id
   AND e.event_type='financial.collaboration.notice_requested'
   AND e.aggregate_type='collaboration' AND e.aggregate_id=n.assignment_id::text
   AND e.payload::jsonb=jsonb_build_object('notice_id', n.notice_id::text)
 ) THEN RAISE EXCEPTION 'notice_attempt_proof_invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER notice_attempt_proof BEFORE INSERT ON financial_notice_attempts
FOR EACH ROW EXECUTE FUNCTION notice_check_attempt_proof();
"""
for model in MODELS[1:]:
    sa.event.listen(
        model.__table__,
        "after_create",
        sa.DDL(
            DENY_MUTATION
            + f"""
CREATE TRIGGER notice_fact_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON {model.__tablename__} FOR EACH STATEMENT
EXECUTE FUNCTION notice_deny_fact_mutation();
"""
        ).execute_if(dialect="postgresql"),
    )
sa.event.listen(
    NoticeDeliveryAttemptModel.__table__,
    "after_create",
    sa.DDL(ATTEMPT_PROOF).execute_if(dialect="postgresql"),
)
