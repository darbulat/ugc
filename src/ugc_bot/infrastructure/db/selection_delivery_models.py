"""Immutable contact payloads, provider outcomes and paid deliveries."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ugc_bot.infrastructure.db.base import Base

ATTEMPTS = sa.Table(
    "paid_selection_delivery_attempts",
    Base.metadata,
    sa.Column("attempt_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "job_id",
        UUID(as_uuid=True),
        sa.ForeignKey("paid_selection_delivery_jobs.job_id"),
        nullable=False,
    ),
    sa.Column(
        "interest_id",
        UUID(as_uuid=True),
        sa.ForeignKey("paid_selection_interests.interest_id"),
        nullable=False,
    ),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        nullable=False,
    ),
    sa.Column(
        "source", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
    ),
    sa.Column("source_hash", sa.String(64), nullable=False),
    sa.Column("number", sa.Integer, nullable=False),
    sa.Column("lease_token", UUID(as_uuid=True), nullable=False, unique=True),
    sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
    sa.Column("channel", sa.String(30)),
    sa.Column("address", sa.String),
    sa.Column("address_kind", sa.String(30), nullable=False),
    sa.Column("locale", sa.String(20), nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("action_url", sa.String),
    sa.Column("action_label", sa.String),
    sa.UniqueConstraint("job_id", "number", name="uq_selection_attempt_number"),
    sa.CheckConstraint(
        "number > 0 AND lease_until > prepared_at AND length(source_hash)=64",
        name="ck_selection_attempt_fence",
    ),
)
OUTCOMES = sa.Table(
    "paid_selection_delivery_outcomes",
    Base.metadata,
    sa.Column("outcome_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "job_id",
        UUID(as_uuid=True),
        sa.ForeignKey("paid_selection_delivery_jobs.job_id"),
        nullable=False,
    ),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        nullable=False,
    ),
    sa.Column(
        "attempt_id",
        UUID(as_uuid=True),
        sa.ForeignKey("paid_selection_delivery_attempts.attempt_id"),
    ),
    sa.Column("kind", sa.String(30), nullable=False),
    sa.Column("status", sa.String(30), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("provider_reference", sa.String),
    sa.Column("reason", sa.String(200)),
    sa.Column("applied", sa.Boolean, nullable=False),
    sa.UniqueConstraint("attempt_id", "kind", name="uq_selection_outcome_kind"),
    sa.CheckConstraint(
        "kind IN ('preflight','started','transport','recovery') "
        "AND status IN ('started','accepted','failed','unknown','obsolete')",
        name="ck_selection_outcome_type",
    ),
    sa.CheckConstraint(
        "(status = 'accepted' AND provider_reference IS NOT NULL "
        "AND length(trim(provider_reference)) > 0) OR "
        "(status <> 'accepted' AND provider_reference IS NULL)",
        name="ck_selection_provider_reference",
    ),
    sa.CheckConstraint(
        "NOT applied OR (kind='transport' AND status='accepted' "
        "AND attempt_id IS NOT NULL)",
        name="ck_selection_applied_outcome",
    ),
)
ACCEPTED = sa.Table(
    "paid_selection_accepted_deliveries",
    Base.metadata,
    sa.Column("delivery_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "outcome_id",
        UUID(as_uuid=True),
        sa.ForeignKey("paid_selection_delivery_outcomes.outcome_id"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "attempt_id",
        UUID(as_uuid=True),
        sa.ForeignKey("paid_selection_delivery_attempts.attempt_id"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "job_id",
        UUID(as_uuid=True),
        sa.ForeignKey("paid_selection_delivery_jobs.job_id"),
        nullable=False,
        unique=True,
    ),
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
    sa.Column(
        "client_id",
        UUID(as_uuid=True),
        sa.ForeignKey("users.user_id"),
        nullable=False,
    ),
    sa.Column(
        "creator_id",
        UUID(as_uuid=True),
        sa.ForeignKey("users.user_id"),
        nullable=False,
    ),
    sa.Column(
        "paid_item_id",
        UUID(as_uuid=True),
        sa.ForeignKey("order_items.paid_item_id"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "assignment_id",
        UUID(as_uuid=True),
        sa.ForeignKey("item_assignments.assignment_id"),
        nullable=False,
        unique=True,
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
        "allocation_key",
        sa.String,
        sa.ForeignKey("payment_item_allocations.allocation_key"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "policy_version",
        sa.String,
        sa.ForeignKey("financial_policy_versions.version"),
        nullable=False,
    ),
    sa.Column("currency", sa.String(3), nullable=False),
    sa.Column("amount_minor", sa.BigInteger, nullable=False),
    sa.Column("instagram_user_id", sa.String, nullable=False),
    sa.Column("source_hash", sa.String(64), nullable=False),
    sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("channel", sa.String(30), nullable=False),
    sa.Column("provider_reference", sa.String, nullable=False),
    sa.UniqueConstraint(
        "order_id", "creator_id", name="uq_selection_delivered_creator"
    ),
    sa.UniqueConstraint(
        "order_id", "instagram_user_id", name="uq_selection_delivered_identity"
    ),
    sa.UniqueConstraint(
        "channel", "provider_reference", name="uq_selection_provider_acceptance"
    ),
    sa.CheckConstraint(
        "currency='RUB' AND amount_minor>0 "
        "AND length(trim(instagram_user_id))>0 "
        "AND length(trim(provider_reference))>0",
        name="ck_selection_accepted_value",
    ),
)
TABLES = (ATTEMPTS, OUTCOMES, ACCEPTED)
for table in TABLES:
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(f"""
CREATE OR REPLACE FUNCTION paid_selection_delivery_deny_mutation()
RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'paid_selection_delivery_immutable' USING ERRCODE='23514';
END $$;
CREATE TRIGGER paid_selection_delivery_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE
ON {table.name} FOR EACH STATEMENT
EXECUTE FUNCTION paid_selection_delivery_deny_mutation();
""").execute_if(dialect="postgresql"),
    )
