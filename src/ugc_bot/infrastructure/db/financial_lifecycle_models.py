"""Immutable approvals/maturity and an item-serialized active-ground pointer."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ugc_bot.infrastructure.db.base import Base


class RateOverrideModel(Base):
    __tablename__ = "financial_rate_overrides"
    __table_args__ = (
        sa.CheckConstraint(
            "side IN ('client','creator') AND rate_bps BETWEEN 1 AND 10000",
            name="ck_approved_override_rate",
        ),
        sa.CheckConstraint(
            "effective_until > effective_from "
            "AND approved_at <= effective_from",
            name="ck_approved_override_period",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_approved_override_reason"
        ),
    )
    override_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    recipient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("users.user_id"), nullable=False
    )
    side: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    rate_bps: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(
        sa.String,
        sa.ForeignKey("financial_policy_versions.version"),
        nullable=False,
    )
    effective_from: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    effective_until: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    approved_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("users.user_id"), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)


class ActiveEconomicGroundModel(Base):
    __tablename__ = "financial_active_grounds"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            [
                "obligation_id",
                "paid_item_id",
                "kind",
                "recipient_id",
                "currency",
            ],
            [
                "financial_obligations.id",
                "financial_obligations.paid_item_id",
                "financial_obligations.kind",
                "financial_obligations.recipient_id",
                "financial_obligations.currency",
            ],
            name="fk_active_ground_scope",
        ),
        sa.CheckConstraint(
            "kind IN ('creator_referral','management')",
            name="ck_active_ground_kind",
        ),
    )
    paid_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    kind: Mapped[str] = mapped_column(sa.String(30), primary_key=True)
    obligation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    recipient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)


class ObligationMaturityModel(Base):
    __tablename__ = "financial_obligation_maturity"
    __table_args__ = (
        sa.UniqueConstraint("obligation_id", name="uq_obligation_maturity"),
        sa.ForeignKeyConstraint(
            ["obligation_id", "assignment_id", "paid_item_id"],
            [
                "financial_obligations.id",
                "financial_obligations.assignment_id",
                "financial_obligations.paid_item_id",
            ],
            name="fk_maturity_obligation_scope",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "assignment_id"],
            [
                "financial_collaboration_schedules.schedule_id",
                "financial_collaboration_schedules.assignment_id",
            ],
            name="fk_maturity_work_schedule",
        ),
        sa.CheckConstraint(
            "release_at > success_final_at "
            "AND recorded_at >= success_final_at "
            "AND length(trim(producer)) > 0",
            name="ck_maturity_provenance",
        ),
    )
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    obligation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    assignment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    paid_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    success_final_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    release_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    producer: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    payload_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)


TABLES = tuple(
    Base.metadata.tables[model.__tablename__]
    for model in (
        RateOverrideModel,
        ActiveEconomicGroundModel,
        ObligationMaturityModel,
    )
)

DENY_MUTATION = """
CREATE OR REPLACE FUNCTION financial_lifecycle_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'financial_lifecycle_fact_immutable' USING ERRCODE='23514';
END $$;
"""
for table in (TABLES[0], TABLES[2]):
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(
            DENY_MUTATION
            + f"""
CREATE TRIGGER financial_lifecycle_fact_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON {table.name} FOR EACH STATEMENT
EXECUTE FUNCTION financial_lifecycle_deny_mutation();
"""
        ).execute_if(dialect="postgresql"),
    )
