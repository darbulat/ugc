"""Immutable weekly summary evidence and a separate delivery projection."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ugc_bot.infrastructure.db.base import Base

_json = sa.JSON().with_variant(JSONB(), "postgresql")
REQUESTS = sa.Table(
    "campaign_digest_requests",
    Base.metadata,
    sa.Column("request_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        nullable=False,
    ),
    sa.Column(
        "recipient_id",
        UUID(as_uuid=True),
        sa.ForeignKey("users.user_id"),
        nullable=False,
    ),
    sa.Column("week_start", sa.Date, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source", _json, nullable=False),
    sa.Column("source_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint(
        "order_id", "recipient_id", "week_start", name="uq_campaign_digest_week"
    ),
    sa.CheckConstraint(
        "length(source_hash)=64 AND extract(isodow FROM week_start)=1",
        name="ck_campaign_digest_request",
    ),
)
JOBS = sa.Table(
    "campaign_digest_jobs",
    Base.metadata,
    sa.Column(
        "request_id",
        UUID(as_uuid=True),
        sa.ForeignKey("campaign_digest_requests.request_id"),
        primary_key=True,
    ),
    sa.Column("state", sa.String(30), nullable=False),
    sa.Column("attempt_id", UUID(as_uuid=True)),
    sa.Column("lease_token", UUID(as_uuid=True)),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.CheckConstraint(
        "state IN ('ready','sending','accepted','failed','unknown','obsolete')",
        name="ck_campaign_digest_job_state",
    ),
    sa.CheckConstraint(
        "state <> 'sending' OR (attempt_id IS NOT NULL "
        "AND lease_token IS NOT NULL AND lease_until IS NOT NULL)",
        name="ck_campaign_digest_job_lease",
    ),
)
ATTEMPTS = sa.Table(
    "campaign_digest_attempts",
    Base.metadata,
    sa.Column("attempt_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "request_id",
        UUID(as_uuid=True),
        sa.ForeignKey("campaign_digest_requests.request_id"),
        nullable=False,
        unique=True,
    ),
    sa.Column("lease_token", UUID(as_uuid=True), nullable=False, unique=True),
    sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source", _json, nullable=False),
    sa.Column("source_hash", sa.String(64), nullable=False),
    sa.Column("channel", sa.String(30), nullable=False),
    sa.Column("address", sa.String, nullable=False),
    sa.Column("address_kind", sa.String(30), nullable=False),
    sa.Column("locale", sa.String(20), nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("action_url", sa.String, nullable=False),
    sa.Column("action_label", sa.String, nullable=False),
    sa.UniqueConstraint(
        "request_id", "attempt_id", name="uq_campaign_digest_attempt_scope"
    ),
    sa.CheckConstraint(
        "lease_until > prepared_at AND length(source_hash)=64",
        name="ck_campaign_digest_attempt_fence",
    ),
)
OUTCOMES = sa.Table(
    "campaign_digest_outcomes",
    Base.metadata,
    sa.Column("outcome_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "request_id",
        UUID(as_uuid=True),
        sa.ForeignKey("campaign_digest_requests.request_id"),
        nullable=False,
    ),
    sa.Column("attempt_id", UUID(as_uuid=True)),
    sa.Column("kind", sa.String(30), nullable=False),
    sa.Column("status", sa.String(30), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("channel", sa.String(30)),
    sa.Column("provider_reference", sa.String),
    sa.Column("reason", sa.String(200)),
    sa.Column("applied", sa.Boolean, nullable=False),
    sa.ForeignKeyConstraint(
        ["request_id", "attempt_id"],
        [
            "campaign_digest_attempts.request_id",
            "campaign_digest_attempts.attempt_id",
        ],
    ),
    sa.UniqueConstraint(
        "attempt_id", "kind", name="uq_campaign_digest_outcome_kind"
    ),
    sa.CheckConstraint(
        "(kind='preflight' AND status='obsolete') OR "
        "(kind='started' AND status='started' AND attempt_id IS NOT NULL) OR "
        "(kind='transport' AND status IN ('accepted','failed','unknown') "
        "AND attempt_id IS NOT NULL) OR "
        "(kind='recovery' AND status='unknown' AND attempt_id IS NOT NULL)",
        name="ck_campaign_digest_outcome_type",
    ),
    sa.CheckConstraint(
        "(status='accepted' AND kind='transport' AND attempt_id IS NOT NULL "
        "AND channel IS NOT NULL AND channel IN ('telegram','max') "
        "AND provider_reference IS NOT NULL "
        "AND length(trim(provider_reference))>0) OR "
        "(status<>'accepted' AND provider_reference IS NULL)",
        name="ck_campaign_digest_outcome_reference",
    ),
    sa.CheckConstraint(
        "NOT applied OR (kind='transport' AND status='accepted')",
        name="ck_campaign_digest_outcome_applied",
    ),
)
sa.Index(
    "uq_campaign_digest_applied_receipt",
    OUTCOMES.c.channel,
    OUTCOMES.c.provider_reference,
    unique=True,
    postgresql_where=OUTCOMES.c.applied,
)
TABLES: tuple[sa.Table, ...] = (REQUESTS, JOBS, ATTEMPTS, OUTCOMES)
for table in (REQUESTS, ATTEMPTS, OUTCOMES):
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(f"""
CREATE OR REPLACE FUNCTION campaign_digest_deny_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'campaign_digest_immutable' USING ERRCODE='23514';
END $$;
CREATE TRIGGER campaign_digest_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON {table.name} FOR EACH STATEMENT
EXECUTE FUNCTION campaign_digest_deny_mutation();
""").execute_if(dialect="postgresql"),
    )
