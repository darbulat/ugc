"""Paid-assignment lifecycle metadata and immutable history constraints."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ugc_bot.infrastructure.db.base import Base

JSON = sa.JSON().with_variant(JSONB(), "postgresql")


class CollaborationModel(Base):
    __tablename__ = "financial_collaborations"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["assignment_id", "paid_item_id"],
            ["item_assignments.assignment_id", "item_assignments.paid_item_id"],
            name="fk_collaboration_assignment_item",
        ),
        sa.ForeignKeyConstraint(
            ["paid_item_id", "order_id", "currency"],
            [
                "order_items.paid_item_id",
                "order_items.order_id",
                "order_items.currency",
            ],
            name="fk_collaboration_item_order",
        ),
        sa.CheckConstraint("version > 0", name="ck_collaboration_version"),
        sa.CheckConstraint(
            "state IN ('assigned','in_progress','success_claimed','disputed',"
            "'success_final','unconfirmed_expired','available','rejected')",
            name="ck_collaboration_state",
        ),
        sa.CheckConstraint(
            "client_id <> creator_id", name="ck_collaboration_distinct_parties"
        ),
        sa.CheckConstraint(
            "currency = 'RUB'", name="ck_collaboration_currency"
        ),
        sa.Index("ix_collaboration_next_transition", "next_transition_at"),
    )

    assignment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    paid_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    client_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("users.user_id"), nullable=False
    )
    creator_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("users.user_id"), nullable=False
    )
    manager_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("users.user_id")
    )
    policy_version: Mapped[str] = mapped_column(
        sa.String,
        sa.ForeignKey("financial_policy_versions.version"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    next_transition_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    record_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


class CollaborationEventModel(Base):
    __tablename__ = "financial_collaboration_events"
    __table_args__ = (
        sa.UniqueConstraint(
            "event_id", "assignment_id", name="uq_collaboration_event_scope"
        ),
        sa.UniqueConstraint(
            "assignment_id", "operation_key", name="uq_collaboration_command"
        ),
        sa.UniqueConstraint(
            "assignment_id", "version", name="uq_collaboration_event_version"
        ),
        sa.CheckConstraint(
            "version > 0 AND length(trim(operation_key)) > 0",
            name="ck_collaboration_event_provenance",
        ),
        sa.CheckConstraint(
            "(actor_id IS NOT NULL AND system_actor IS NULL) OR "
            "(actor_id IS NULL AND system_actor IS NOT NULL "
            "AND length(trim(system_actor)) > 0)",
            name="ck_collaboration_event_actor",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    assignment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("financial_collaborations.assignment_id"),
        nullable=False,
    )
    operation_key: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("users.user_id")
    )
    system_actor: Mapped[str | None] = mapped_column(sa.String(100))
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


class CollaborationNoticeModel(Base):
    __tablename__ = "financial_collaboration_notices"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["source_event_id", "assignment_id"],
            [
                "financial_collaboration_events.event_id",
                "financial_collaboration_events.assignment_id",
            ],
            name="fk_collaboration_notice_event_scope",
        ),
        sa.UniqueConstraint(
            "assignment_id",
            "purpose",
            "recipient_id",
            name="uq_collaboration_notice_purpose",
        ),
        sa.CheckConstraint(
            "purpose IN ('objection','confirmation')",
            name="ck_collaboration_notice_purpose",
        ),
    )

    notice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    assignment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("financial_collaborations.assignment_id"),
        nullable=False,
    )
    source_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    recipient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("users.user_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


class CollaborationReleaseScheduleModel(Base):
    __tablename__ = "financial_collaboration_schedules"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["source_event_id", "assignment_id"],
            [
                "financial_collaboration_events.event_id",
                "financial_collaboration_events.assignment_id",
            ],
            name="fk_collaboration_schedule_event_scope",
        ),
        sa.UniqueConstraint(
            "assignment_id", name="uq_collaboration_release_assignment"
        ),
        sa.UniqueConstraint(
            "source_event_id", name="uq_collaboration_release_source"
        ),
        sa.UniqueConstraint(
            "schedule_id", "assignment_id", name="uq_work_maturity_scope"
        ),
        sa.CheckConstraint(
            "release_at > success_final_at",
            name="ck_collaboration_release_after_success",
        ),
    )

    schedule_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    assignment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("financial_collaborations.assignment_id"),
        nullable=False,
    )
    source_event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )
    success_final_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    release_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


MODELS = (
    CollaborationModel,
    CollaborationEventModel,
    CollaborationNoticeModel,
    CollaborationReleaseScheduleModel,
)
TABLES: tuple[sa.Table, ...] = tuple(
    Base.metadata.tables[model.__tablename__] for model in MODELS
)

DENY_MUTATION = """
CREATE OR REPLACE FUNCTION collaboration_deny_fact_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'collaboration_fact_immutable' USING ERRCODE='23514';
END $$;
"""

for model in MODELS[1:]:
    sa.event.listen(
        model.__table__,
        "after_create",
        sa.DDL(
            DENY_MUTATION
            + f"""
CREATE TRIGGER collaboration_fact_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON {model.__tablename__} FOR EACH STATEMENT
EXECUTE FUNCTION collaboration_deny_fact_mutation();
"""
        ).execute_if(dialect="postgresql"),
    )
