"""Immutable confirmed interest and its delivery queue projection."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.base import Base

INTERESTS = sa.Table(
    "paid_selection_interests",
    Base.metadata,
    sa.Column("interest_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        nullable=False,
    ),
    sa.Column(
        "creator_id",
        UUID(as_uuid=True),
        sa.ForeignKey("users.user_id"),
        nullable=False,
    ),
    sa.Column(
        "client_id",
        UUID(as_uuid=True),
        sa.ForeignKey("users.user_id"),
        nullable=False,
    ),
    sa.Column(
        "payment_id",
        UUID(as_uuid=True),
        sa.ForeignKey("payments.payment_id"),
        nullable=False,
    ),
    sa.Column(
        "capture_event_id",
        UUID(as_uuid=True),
        sa.ForeignKey("outbox_events.event_id"),
        nullable=False,
    ),
    sa.Column(
        "policy_version",
        sa.String,
        sa.ForeignKey("financial_policy_versions.version"),
        nullable=False,
    ),
    sa.Column("currency", sa.String(3), nullable=False),
    sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("instagram_user_id", sa.String, nullable=False),
    sa.Column("instagram_url", sa.String, nullable=False),
    sa.Column("accepted", sa.Boolean, nullable=False),
    sa.Column("paid_item_id", UUID(as_uuid=True)),
    sa.Column("assignment_id", UUID(as_uuid=True), unique=True),
    sa.Column("manager_id", UUID(as_uuid=True), sa.ForeignKey("users.user_id")),
    sa.UniqueConstraint(
        "order_id", "creator_id", name="uq_selection_order_creator"
    ),
    sa.UniqueConstraint(
        "order_id", "instagram_user_id", name="uq_selection_order_instagram"
    ),
    sa.ForeignKeyConstraint(
        ["assignment_id", "paid_item_id"],
        ["item_assignments.assignment_id", "item_assignments.paid_item_id"],
    ),
    sa.ForeignKeyConstraint(
        ["paid_item_id", "order_id", "currency"],
        [
            "order_items.paid_item_id",
            "order_items.order_id",
            "order_items.currency",
        ],
        name="fk_selection_item_order",
    ),
    sa.CheckConstraint("currency = 'RUB'", name="ck_selection_currency"),
    sa.CheckConstraint(
        "client_id <> creator_id AND length(trim(instagram_user_id)) > 0",
        name="ck_selection_verified_party",
    ),
    sa.CheckConstraint(
        "(accepted AND assignment_id IS NOT NULL AND paid_item_id IS NOT NULL) "
        "OR (NOT accepted AND assignment_id IS NULL AND paid_item_id IS NULL "
        "AND manager_id IS NULL)",
        name="ck_selection_interest_allocation",
    ),
)

JOBS = sa.Table(
    "paid_selection_delivery_jobs",
    Base.metadata,
    sa.Column("job_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "interest_id",
        UUID(as_uuid=True),
        sa.ForeignKey("paid_selection_interests.interest_id"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        nullable=False,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("state", sa.String(30), nullable=False),
    sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("current_attempt_id", UUID(as_uuid=True)),
    sa.Column("lease_token", UUID(as_uuid=True)),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.CheckConstraint(
        "state IN ('ready','sending','accepted','failed','unknown','obsolete') "
        "AND attempt_count >= 0",
        name="ck_selection_delivery_job",
    ),
    sa.Index(
        "ix_selection_delivery_candidates", "state", "lease_until", "created_at"
    ),
)

TABLES = (INTERESTS, JOBS)
DENY_MUTATION = """
CREATE OR REPLACE FUNCTION paid_selection_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'paid_selection_fact_immutable' USING ERRCODE='23514';
END $$;
"""
sa.event.listen(
    INTERESTS,
    "after_create",
    sa.DDL(
        DENY_MUTATION
        + """
CREATE TRIGGER paid_selection_fact_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON paid_selection_interests FOR EACH STATEMENT
EXECUTE FUNCTION paid_selection_deny_mutation();
"""
    ).execute_if(dialect="postgresql"),
)
