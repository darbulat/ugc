"""Append-only campaign policy, publisher and consent facts; no sends."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ugc_bot.infrastructure.db.base import Base

JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def user(name, **kwargs):
    return sa.Column(
        name, UUID(as_uuid=True), sa.ForeignKey("users.user_id"), **kwargs
    )


COMMANDS = sa.Table(
    "campaign_foundation_commands",
    Base.metadata,
    user("actor_id", primary_key=True),
    sa.Column("operation_key", sa.String(256), primary_key=True),
    sa.Column("action", sa.String(20), nullable=False),
    sa.Column("payload_hash", sa.String(64), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("result", JSON, nullable=False),
    sa.CheckConstraint(
        "action IN ('publish','suspend','grant','revoke','consent',"
        "'unsubscribe') AND length(trim(operation_key))>0 "
        "AND length(payload_hash)=64",
        name="ck_campaign_command_proof",
    ),
)


def provenance():
    return (
        user("actor_id", nullable=False),
        sa.Column("operation_key", sa.String(256), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ("actor_id", "operation_key"),
            (
                "campaign_foundation_commands.actor_id",
                "campaign_foundation_commands.operation_key",
            ),
        ),
        sa.CheckConstraint("version>0", name="positive_version"),
    )


POLICIES = sa.Table(
    "campaign_policy_events",
    Base.metadata,
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column(
        "publication_version",
        sa.Integer,
        sa.ForeignKey("campaign_policy_events.version"),
        nullable=False,
    ),
    sa.Column("terms_version", sa.String(1000), nullable=False),
    sa.Column("terms_hash", sa.String(64), nullable=False),
    sa.Column("default_locale", sa.String(10), nullable=False),
    sa.Column("terms", JSON, nullable=False),
    sa.Column("limits", JSON, nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    *provenance(),
    sa.CheckConstraint(
        "length(trim(terms_version))>0 AND length(terms_hash)=64 "
        "AND length(trim(reason))>0 AND publication_version<=version",
        name="ck_campaign_policy_proof",
    ),
)
PUBLISHERS = sa.Table(
    "campaign_publisher_events",
    Base.metadata,
    user("owner_id", primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("active", sa.Boolean, nullable=False),
    sa.Column(
        "policy_version",
        sa.Integer,
        sa.ForeignKey("campaign_policy_events.version"),
        nullable=False,
    ),
    sa.Column("reason", sa.Text, nullable=False),
    *provenance(),
    sa.CheckConstraint(
        "length(trim(reason))>0", name="ck_campaign_publisher_proof"
    ),
)
CONSENTS = sa.Table(
    "campaign_consent_events",
    Base.metadata,
    user("creator_id", primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    user("owner_id", nullable=False),
    sa.Column("canonical_identity", sa.Text, nullable=False),
    sa.Column("binding_created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "policy_version",
        sa.Integer,
        sa.ForeignKey("campaign_policy_events.version"),
        nullable=False,
    ),
    sa.Column("terms_version", sa.String(1000), nullable=False),
    sa.Column("terms_hash", sa.String(64), nullable=False),
    sa.Column("active", sa.Boolean, nullable=False),
    *provenance(),
    sa.CheckConstraint(
        "actor_id=creator_id AND creator_id<>owner_id "
        "AND length(trim(canonical_identity))>0 AND length(terms_hash)=64 "
        "AND length(trim(terms_version))>0",
        name="ck_campaign_consent_proof",
    ),
)
TABLES = (COMMANDS, POLICIES, PUBLISHERS, CONSENTS)
STREAMS = {"policy": POLICIES, "publisher": PUBLISHERS, "consent": CONSENTS}
DENY_MUTATION = """
CREATE OR REPLACE FUNCTION campaign_foundation_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'campaign_fact_immutable' USING ERRCODE='23514';
END $$;
"""
for table in TABLES:
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(
            DENY_MUTATION
            + f"""
CREATE TRIGGER campaign_fact_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON {table.name} FOR EACH STATEMENT
EXECUTE FUNCTION campaign_foundation_deny_mutation();
"""
        ).execute_if(dialect="postgresql"),
    )
