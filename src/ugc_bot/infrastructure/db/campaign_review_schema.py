"""Immutable own draft identities, command receipts and revision facts."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def draft_tables(metadata):
    json = sa.JSON().with_variant(JSONB(), "postgresql")
    commands = sa.Table(
        "campaign_draft_commands",
        metadata,
        sa.Column(
            "actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            primary_key=True,
        ),
        sa.Column("operation_key", sa.String(256), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", json, nullable=False),
        sa.CheckConstraint(
            "length(trim(operation_key))>0 AND length(payload_hash)=64",
            name="ck_campaign_draft_command_proof",
        ),
    )
    drafts = sa.Table(
        "campaign_drafts",
        metadata,
        sa.Column("campaign_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("operation_key", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "campaign_id", "owner_id", name="uq_campaign_draft_owner"
        ),
        sa.ForeignKeyConstraint(
            ("owner_id", "operation_key"),
            (
                "campaign_draft_commands.actor_id",
                "campaign_draft_commands.operation_key",
            ),
        ),
    )
    revisions = sa.Table(
        "campaign_draft_revisions",
        metadata,
        sa.Column("campaign_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("operation_key", sa.String(256), nullable=False),
        sa.Column(
            "policy_version",
            sa.Integer,
            sa.ForeignKey("campaign_policy_events.version"),
            nullable=False,
        ),
        sa.Column("terms_hash", sa.String(64), nullable=False),
        sa.Column("grant_version", sa.Integer, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", json, nullable=False),
        sa.Column("segment", json, nullable=False),
        sa.Column(
            "revision_digest", sa.String(64), nullable=False, unique=True
        ),
        sa.ForeignKeyConstraint(
            ("campaign_id", "owner_id"),
            ("campaign_drafts.campaign_id", "campaign_drafts.owner_id"),
        ),
        sa.ForeignKeyConstraint(
            ("owner_id", "operation_key"),
            (
                "campaign_draft_commands.actor_id",
                "campaign_draft_commands.operation_key",
            ),
        ),
        sa.ForeignKeyConstraint(
            ("owner_id", "grant_version"),
            (
                "campaign_publisher_events.owner_id",
                "campaign_publisher_events.version",
            ),
        ),
        sa.UniqueConstraint(
            "owner_id",
            "operation_key",
            name="uq_campaign_draft_revision_command",
        ),
        sa.CheckConstraint(
            "version>0 AND grant_version>0 AND length(terms_hash)=64 "
            "AND length(revision_digest)=64",
            name="ck_campaign_draft_revision_proof",
        ),
    )
    return commands, drafts, revisions


def immutability_sql(tables):
    return """
CREATE OR REPLACE FUNCTION campaign_drafts_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'campaign_fact_immutable' USING ERRCODE='23514';
END $$;
""" + "\n".join(
        "CREATE TRIGGER campaign_draft_immutable "
        f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {table.name} "
        "FOR EACH STATEMENT EXECUTE FUNCTION campaign_drafts_deny_mutation();"
        for table in tables
    )
