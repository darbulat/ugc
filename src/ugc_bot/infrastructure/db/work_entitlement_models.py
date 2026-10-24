"""Immutable transactional assessment of persisted collaboration events."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ugc_bot.infrastructure.db.base import Base

WORK_ASSESSMENTS = sa.Table(
    "financial_work_assessments",
    Base.metadata,
    sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("assignment_id", UUID(as_uuid=True), nullable=False),
    sa.Column("paid_item_id", UUID(as_uuid=True), nullable=False),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        nullable=False,
    ),
    sa.Column(
        "payment_id",
        UUID(as_uuid=True),
        sa.ForeignKey("payments.payment_id"),
        nullable=False,
    ),
    sa.Column("source_hash", sa.String(64), nullable=False),
    sa.Column(
        "assessment",
        sa.JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    ),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["event_id", "assignment_id"],
        [
            "financial_collaboration_events.event_id",
            "financial_collaboration_events.assignment_id",
        ],
        name="fk_work_assessment_source",
    ),
    sa.ForeignKeyConstraint(
        ["assignment_id", "paid_item_id"],
        ["item_assignments.assignment_id", "item_assignments.paid_item_id"],
        name="fk_work_assessment_assignment",
    ),
)
TABLES = (WORK_ASSESSMENTS,)
sa.event.listen(
    WORK_ASSESSMENTS,
    "after_create",
    sa.DDL("""
CREATE OR REPLACE FUNCTION financial_work_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'financial_work_assessment_immutable' USING ERRCODE='23514';
END $$;
CREATE TRIGGER financial_work_assessment_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON financial_work_assessments
FOR EACH STATEMENT EXECUTE FUNCTION financial_work_deny_mutation();
""").execute_if(dialect="postgresql"),
)
