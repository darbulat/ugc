"""Immutable manual marketing evidence, distinct from the financial journal."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def analytics_tables(metadata):
    json = sa.JSON().with_variant(JSONB(), "postgresql")

    def uid(name, **kw):
        return sa.Column(name, UUID(as_uuid=True), **kw)

    def at():
        return sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False
        )

    sources = sa.Table(
        "campaign_analytics_sources",
        metadata,
        uid("source_id", primary_key=True),
        uid("subject_id", nullable=False, index=True),
        sa.Column("subject_type", sa.String(16), nullable=False),
        uid("owner_id", nullable=False),
        uid("actor_id", nullable=False),
        sa.Column("document", json, nullable=False),
        at(),
    )
    events = sa.Table(
        "campaign_analytics_events",
        metadata,
        uid("event_id", primary_key=True),
        uid("source_id", nullable=False),
        sa.Column("source_name", sa.String(128), nullable=False),
        sa.Column("account_label", sa.String(128), nullable=False),
        sa.Column("external_event_id", sa.String(256), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("document", json, nullable=False),
        at(),
        sa.ForeignKeyConstraint(
            ("source_id",), ("campaign_analytics_sources.source_id",)
        ),
        sa.UniqueConstraint(
            "source_name",
            "account_label",
            "external_event_id",
            name="uq_campaign_analytics_external_event",
        ),
    )
    actions = sa.Table(
        "campaign_analytics_actions",
        metadata,
        uid("action_id", primary_key=True),
        uid("source_id", nullable=False),
        uid("actor_id", nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("proof_reference", sa.String(2048), nullable=False),
        sa.Column("reason", sa.String(2048), nullable=False),
        at(),
        sa.ForeignKeyConstraint(
            ("source_id",), ("campaign_analytics_sources.source_id",)
        ),
        sa.UniqueConstraint(
            "source_id", "action", name="uq_campaign_analytics_source_action"
        ),
    )
    commands = sa.Table(
        "campaign_analytics_commands",
        metadata,
        uid("actor_id", primary_key=True),
        sa.Column("operation_key", sa.String(256), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", json, nullable=False),
        at(),
    )
    pilots = sa.Table(
        "campaign_analytics_paid_pilots",
        metadata,
        uid("pilot_id", primary_key=True),
        uid("subject_id", nullable=False),
        sa.Column("subject_type", sa.String(16), nullable=False),
        uid("actor_id", nullable=False),
        sa.Column(
            "payment_reference", sa.String(256), nullable=False, unique=True
        ),
        sa.Column("paid_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("proof_reference", sa.String(2048), nullable=False),
        at(),
        sa.UniqueConstraint(
            "subject_type",
            "subject_id",
            name="uq_campaign_analytics_paid_subject",
        ),
        sa.CheckConstraint(
            "paid_minor > 0", name="ck_campaign_analytics_paid_positive"
        ),
    )
    return sources, events, actions, commands, pilots


def immutability_sql(tables):
    return """CREATE OR REPLACE FUNCTION campaign_analytics_deny_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'campaign_analytics_immutable' USING ERRCODE='23514'; END $$;
""" + "\n".join(
        "CREATE TRIGGER campaign_analytics_immutable "
        f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {table.name} "
        "FOR EACH STATEMENT EXECUTE FUNCTION "
        "campaign_analytics_deny_mutation();"
        for table in tables
    )
