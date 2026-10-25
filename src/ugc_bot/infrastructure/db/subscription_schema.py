"""Immutable manual payment evidence and published own-network tariffs."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def subscription_table(metadata):
    return sa.Table(
        "manager_subscription_events",
        metadata,
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("sequence", sa.BigInteger, nullable=False, unique=True),
        sa.Column(
            "actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("operation_key", sa.String(256), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "result",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_reference", sa.String(1000), unique=True),
        sa.Column("tariff_version", sa.String(1000), unique=True),
        sa.UniqueConstraint(
            "actor_id", "operation_key", name="uq_subscription_actor_operation"
        ),
        sa.CheckConstraint(
            "action IN ('publish','accept_payment','cancel',"
            "'enable_automation')",
            name="ck_subscription_action",
        ),
        sa.CheckConstraint("sequence > 0", name="ck_subscription_sequence"),
    )


SUBSCRIPTION_GUARDS = """
CREATE OR REPLACE FUNCTION subscription_fact_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'subscription_fact_immutable' USING ERRCODE='23514';
END $$;
CREATE TRIGGER subscription_no_mutation
BEFORE UPDATE OR DELETE OR TRUNCATE ON manager_subscription_events
FOR EACH STATEMENT EXECUTE FUNCTION subscription_fact_immutable();
CREATE OR REPLACE FUNCTION subscription_check_authority() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    IF NOT EXISTS(SELECT1 FROM users WHERE user_id=NEW.actor_id
       AND status='active'
       AND (NEW.action='cancel' OR admin=true)) THEN
        RAISE EXCEPTION 'subscription_current_authority_required';
    END IF;
    IF NEW.action='cancel' AND NEW.actor_id<>NEW.member_id THEN
        RAISE EXCEPTION 'subscription_cancel_ownership_required';
    END IF;
    IF (NEW.action='publish') IS DISTINCT FROM (NEW.tariff_version IS NOT NULL)
       OR (NEW.action='accept_payment') IS DISTINCT FROM
          (NEW.payment_reference IS NOT NULL)
       OR length(trim(NEW.payload->>'reason'))=0 THEN
        RAISE EXCEPTION 'subscription_provenance_required';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER subscription_authority
BEFORE INSERT ON manager_subscription_events
FOR EACH ROW EXECUTE FUNCTION subscription_check_authority();
""".replace("SELECT1", "SELECT 1")
