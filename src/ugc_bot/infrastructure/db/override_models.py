"""Append-only command receipts and per-approval temporal audit facts."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ugc_bot.infrastructure.db.base import Base

COMMANDS = sa.Table(
    "financial_override_commands",
    Base.metadata,
    sa.Column("operation_key", sa.String(256), primary_key=True),
    sa.Column("payload_hash", sa.String(64), nullable=False),
    sa.Column(
        "actor_id",
        UUID(as_uuid=True),
        sa.ForeignKey("users.user_id"),
        nullable=False,
    ),
    sa.Column("action", sa.String(20), nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "result", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
    ),
    sa.CheckConstraint(
        "action IN ('create','revoke','supersede')",
        name="ck_override_command_action",
    ),
    sa.CheckConstraint(
        "length(trim(reason))>0 AND length(trim(operation_key))>0",
        name="ck_override_command_provenance",
    ),
)
EVENTS = sa.Table(
    "financial_override_events",
    Base.metadata,
    sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "operation_key",
        sa.String(256),
        sa.ForeignKey("financial_override_commands.operation_key"),
        nullable=False,
    ),
    sa.Column(
        "override_id",
        UUID(as_uuid=True),
        sa.ForeignKey("financial_rate_overrides.override_id"),
        nullable=False,
    ),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("event_type", sa.String(20), nullable=False),
    sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "replacement_id",
        UUID(as_uuid=True),
        sa.ForeignKey("financial_rate_overrides.override_id"),
    ),
    sa.Column(
        "actor_id",
        UUID(as_uuid=True),
        sa.ForeignKey("users.user_id"),
        nullable=False,
    ),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "override_id", "version", name="uq_override_event_version"
    ),
    sa.CheckConstraint(
        "version>0 AND event_type IN ('created','revoked','superseded')",
        name="ck_override_event_version",
    ),
    sa.CheckConstraint(
        "effective_at>=recorded_at AND length(trim(reason))>0",
        name="ck_override_event_time",
    ),
    sa.CheckConstraint(
        "(event_type='created' AND version=1 AND replacement_id IS NULL) OR "
        "(event_type='revoked' AND version>1 AND replacement_id IS NULL) OR "
        "(event_type='superseded' AND version>1 "
        "AND replacement_id IS NOT NULL AND replacement_id<>override_id)",
        name="ck_override_event_shape",
    ),
)
sa.Index(
    "uq_override_revocation",
    EVENTS.c.override_id,
    unique=True,
    postgresql_where=sa.text("event_type IN ('revoked','superseded')"),
    sqlite_where=sa.text("event_type IN ('revoked','superseded')"),
)
TABLES = (COMMANDS, EVENTS)
DENY_MUTATION = """
CREATE OR REPLACE FUNCTION financial_override_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'financial_override_fact_immutable' USING ERRCODE='23514';
END $$;
"""
for table in TABLES:
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(
            DENY_MUTATION
            + f"""
CREATE TRIGGER financial_override_fact_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON {table.name} FOR EACH STATEMENT
EXECUTE FUNCTION financial_override_deny_mutation();
"""
        ).execute_if(dialect="postgresql"),
    )
