"""Requested/unpaid accompaniment facts; no management entitlement."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ugc_bot.infrastructure.db.base import Base

json_type = sa.JSON().with_variant(JSONB(), "postgresql")
metadata = Base.metadata

INTAKE_RECEIPTS = sa.Table(
    "order_intake_receipts",
    metadata,
    sa.Column("request_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        nullable=False,
        unique=True,
    ),
    sa.Column("client_id", UUID(as_uuid=True), nullable=False),
    sa.Column("operation_key", sa.String(256), nullable=False),
    sa.Column("payload_hash", sa.String(64), nullable=False),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("result", json_type, nullable=False),
    sa.UniqueConstraint(
        "client_id", "operation_key", name="uq_intake_client_operation"
    ),
)

ACCOMPANIMENT_LEADS = sa.Table(
    "accompaniment_leads",
    metadata,
    sa.Column("lead_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "request_id",
        UUID(as_uuid=True),
        sa.ForeignKey("order_intake_receipts.request_id"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        nullable=False,
        unique=True,
    ),
    sa.Column("client_id", UUID(as_uuid=True), nullable=False),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("contact_reference", sa.String(500), nullable=False),
    sa.Column("selected_ordinals", json_type, nullable=False),
    sa.Column("state", sa.String(30), nullable=False),
    sa.CheckConstraint(
        "state='requested_unpaid'", name="ck_lead_requested_unpaid"
    ),
)

LEAD_OUTBOX = sa.Table(
    "accompaniment_lead_outbox",
    metadata,
    sa.Column(
        "lead_id",
        UUID(as_uuid=True),
        sa.ForeignKey("accompaniment_leads.lead_id"),
        primary_key=True,
    ),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        nullable=False,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expanded_at", sa.DateTime(timezone=True)),
)

TABLES: tuple[sa.Table, ...] = (
    INTAKE_RECEIPTS,
    ACCOMPANIMENT_LEADS,
    LEAD_OUTBOX,
)

TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION intake_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'order_intake_fact_immutable' USING ERRCODE='23514';
END $$;
CREATE TRIGGER intake_receipt_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON order_intake_receipts
FOR EACH STATEMENT EXECUTE FUNCTION intake_deny_mutation();
CREATE TRIGGER accompaniment_lead_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON accompaniment_leads
FOR EACH STATEMENT EXECUTE FUNCTION intake_deny_mutation();

CREATE OR REPLACE FUNCTION intake_validate_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE owner uuid; actual_count integer; matched_count integer;
BEGIN
    SELECT advertiser_id INTO owner FROM orders
        WHERE order_id=NEW.order_id AND created_at=NEW.requested_at;
    IF owner IS DISTINCT FROM NEW.client_id
       OR NEW.result->>'order_id' IS DISTINCT FROM NEW.order_id::text
       OR NEW.result->>'request_id' IS DISTINCT FROM NEW.request_id::text
       OR NEW.result->>'honorarium_payment' IS DISTINCT FROM 'paid_direct' THEN
        RAISE EXCEPTION 'intake_source_mismatch';
    END IF;
    SELECT count(*) INTO actual_count FROM order_items
        WHERE order_id=NEW.order_id;
    SELECT count(DISTINCT actual.paid_item_id) INTO matched_count
        FROM jsonb_array_elements(NEW.result->'items') requested
        JOIN order_items actual
          ON actual.paid_item_id=(requested->>'paid_item_id')::uuid
         AND actual.order_id=NEW.order_id
         AND actual.ordinal=(requested->>'ordinal')::integer
         AND actual.selection_minor=50000
         AND actual.selection_minor=(requested->>'selection_minor')::bigint
         AND actual.accompaniment_minor IN (0,120000)
         AND actual.accompaniment_minor=
             (requested->>'accompaniment_minor')::bigint
         AND actual.currency=NEW.result->>'currency'
         AND actual.policy_version=NEW.result->>'policy_version'
         AND actual.selection_due_at=
             (NEW.result->>'selection_due_at')::timestamptz
         AND actual.quote_payload->>'terms_reference'=
             NEW.result->>'terms_reference';
    IF actual_count <> 30 OR matched_count <> 30
       OR jsonb_array_length(NEW.result->'items') <> 30 THEN
        RAISE EXCEPTION 'intake_quote_mismatch';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER intake_receipt_source BEFORE INSERT ON order_intake_receipts
FOR EACH ROW EXECUTE FUNCTION intake_validate_source();

CREATE OR REPLACE FUNCTION accompaniment_validate_lead() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE receipt record; selected jsonb;
BEGIN
    SELECT * INTO receipt FROM order_intake_receipts
        WHERE request_id=NEW.request_id;
    SELECT jsonb_agg((item->>'ordinal')::integer
        ORDER BY (item->>'ordinal')::integer) INTO selected
        FROM jsonb_array_elements(receipt.result->'items') item
        WHERE (item->>'accompaniment_minor')::bigint=120000;
    IF receipt.order_id IS DISTINCT FROM NEW.order_id
       OR receipt.client_id IS DISTINCT FROM NEW.client_id
       OR receipt.requested_at IS DISTINCT FROM NEW.requested_at
       OR receipt.result->>'lead_id' IS DISTINCT FROM NEW.lead_id::text
       OR selected IS NULL OR selected IS DISTINCT FROM NEW.selected_ordinals
       OR length(trim(NEW.contact_reference))=0 THEN
        RAISE EXCEPTION 'accompaniment_lead_source_mismatch';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER accompaniment_lead_source BEFORE INSERT ON accompaniment_leads
FOR EACH ROW EXECUTE FUNCTION accompaniment_validate_lead();
"""

LEAD_DELIVERIES = sa.Table(
    "accompaniment_lead_deliveries",
    metadata,
    sa.Column("job_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "lead_id",
        UUID(as_uuid=True),
        sa.ForeignKey("accompaniment_leads.lead_id"),
        nullable=False,
    ),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        nullable=False,
    ),
    sa.Column("recipient_id", UUID(as_uuid=True), nullable=False),
    sa.Column("state", sa.String(20), nullable=False),
    sa.Column("attempt_count", sa.Integer, nullable=False),
    sa.Column("current_attempt_id", UUID(as_uuid=True)),
    sa.Column("lease_token", UUID(as_uuid=True)),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.UniqueConstraint(
        "lead_id", "recipient_id", name="uq_lead_admin_delivery"
    ),
    sa.UniqueConstraint(
        "job_id",
        "lead_id",
        "order_id",
        "recipient_id",
        name="uq_lead_job_scope",
    ),
    sa.CheckConstraint(
        "state IN ('ready','sending','accepted','failed','unknown','obsolete')",
        name="ck_lead_job_state",
    ),
)

LEAD_ATTEMPTS = sa.Table(
    "accompaniment_lead_attempts",
    metadata,
    sa.Column("attempt_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("job_id", UUID(as_uuid=True), nullable=False),
    sa.Column("lead_id", UUID(as_uuid=True), nullable=False),
    sa.Column("order_id", UUID(as_uuid=True), nullable=False),
    sa.Column("recipient_id", UUID(as_uuid=True), nullable=False),
    sa.Column("number", sa.Integer, nullable=False),
    sa.Column("lease_token", UUID(as_uuid=True), nullable=False),
    sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
    sa.Column("channel", sa.String(20)),
    sa.Column("address", sa.Text),
    sa.Column("address_kind", sa.String(20), nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("action_url", sa.Text),
    sa.Column("action_label", sa.Text),
    sa.UniqueConstraint("job_id", "number", name="uq_lead_attempt_number"),
    sa.ForeignKeyConstraint(
        ["job_id", "lead_id", "order_id", "recipient_id"],
        [
            "accompaniment_lead_deliveries." + c
            for c in ("job_id", "lead_id", "order_id", "recipient_id")
        ],
    ),
    sa.CheckConstraint(
        "number > 0 AND lease_until > prepared_at", name="ck_lead_attempt_lease"
    ),
)

LEAD_OUTCOMES = sa.Table(
    "accompaniment_lead_outcomes",
    metadata,
    sa.Column("outcome_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "attempt_id",
        UUID(as_uuid=True),
        sa.ForeignKey("accompaniment_lead_attempts.attempt_id"),
        nullable=False,
    ),
    sa.Column(
        "job_id",
        UUID(as_uuid=True),
        sa.ForeignKey("accompaniment_lead_deliveries.job_id"),
        nullable=False,
    ),
    sa.Column("lead_id", UUID(as_uuid=True), nullable=False),
    sa.Column("order_id", UUID(as_uuid=True), nullable=False),
    sa.Column("kind", sa.String(20), nullable=False),
    sa.Column("status", sa.String(20), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("provider_reference", sa.Text),
    sa.Column("reason", sa.Text),
    sa.Column("applied", sa.Boolean, nullable=False),
    sa.Column("actor_id", UUID(as_uuid=True)),
    sa.Column("operation_key", sa.String(256), unique=True),
    sa.Column("payload_hash", sa.String(64)),
    sa.UniqueConstraint("attempt_id", "kind", name="uq_lead_attempt_outcome"),
    sa.CheckConstraint(
        "kind IN ('result','recovery','retry')", name="ck_lead_outcome_kind"
    ),
    sa.CheckConstraint(
        "status <> 'accepted' OR (provider_reference IS NOT NULL "
        "AND length(trim(provider_reference)) > 0)",
        name="ck_lead_acceptance_reference",
    ),
)

TABLES += (LEAD_DELIVERIES, LEAD_ATTEMPTS, LEAD_OUTCOMES)
TRIGGER_SQL += """
CREATE TRIGGER accompaniment_attempt_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON accompaniment_lead_attempts
FOR EACH STATEMENT EXECUTE FUNCTION intake_deny_mutation();
CREATE TRIGGER accompaniment_outcome_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON accompaniment_lead_outcomes
FOR EACH STATEMENT EXECUTE FUNCTION intake_deny_mutation();
CREATE OR REPLACE FUNCTION accompaniment_attempt_source() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE admin_user record; job record; address text;
    channel text; kind text;
BEGIN
    SELECT * INTO job FROM accompaniment_lead_deliveries
        WHERE job_id=NEW.job_id;
    SELECT * INTO admin_user FROM users WHERE user_id=NEW.recipient_id;
    IF NOT COALESCE(admin_user.admin,false) OR admin_user.status <> 'active'
       OR job.state <> 'ready' OR NEW.number <> job.attempt_count+1 THEN
        RAISE EXCEPTION 'lead_attempt_source_mismatch';
    END IF;
    IF NULLIF(trim(admin_user.telegram_id),'') IS NOT NULL THEN
        channel := 'telegram'; address := admin_user.telegram_id;
        kind := 'chat_id';
    ELSIF NULLIF(trim(admin_user.max_chat_id),'') IS NOT NULL THEN
        channel := 'max'; address := admin_user.max_chat_id; kind := 'chat_id';
    ELSE
        channel := 'max'; address := admin_user.max_id; kind := 'user_id';
    END IF;
    IF (NEW.channel, NEW.address, NEW.address_kind)
       IS DISTINCT FROM (channel, address, kind) THEN
        RAISE EXCEPTION 'lead_attempt_contact_mismatch';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER accompaniment_attempt_proof
BEFORE INSERT ON accompaniment_lead_attempts
FOR EACH ROW EXECUTE FUNCTION accompaniment_attempt_source();
CREATE OR REPLACE FUNCTION accompaniment_outcome_source() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE attempt record;
BEGIN
    SELECT * INTO attempt FROM accompaniment_lead_attempts
        WHERE attempt_id=NEW.attempt_id;
    IF (NEW.job_id,NEW.lead_id,NEW.order_id) IS DISTINCT FROM
       (attempt.job_id,attempt.lead_id,attempt.order_id) THEN
        RAISE EXCEPTION 'lead_outcome_source_mismatch';
    END IF;
    IF NEW.kind='retry' AND (NEW.operation_key IS NULL OR NEW.reason IS NULL
       OR NOT EXISTS (SELECT 1 FROM users WHERE user_id=NEW.actor_id
            AND admin AND status='active')) THEN
        RAISE EXCEPTION 'lead_retry_admin_required';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER accompaniment_outcome_proof
BEFORE INSERT ON accompaniment_lead_outcomes
FOR EACH ROW EXECUTE FUNCTION accompaniment_outcome_source();

CREATE TRIGGER accompaniment_queue_retained
BEFORE DELETE OR TRUNCATE ON accompaniment_lead_outbox
FOR EACH STATEMENT EXECUTE FUNCTION intake_deny_mutation();
CREATE TRIGGER accompaniment_delivery_retained
BEFORE DELETE OR TRUNCATE ON accompaniment_lead_deliveries
FOR EACH STATEMENT EXECUTE FUNCTION intake_deny_mutation();

CREATE OR REPLACE FUNCTION accompaniment_queue_source() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE lead record;
BEGIN
    SELECT * INTO lead FROM accompaniment_leads WHERE lead_id=NEW.lead_id;
    IF NOT FOUND OR (NEW.order_id,NEW.created_at) IS DISTINCT FROM
       (lead.order_id,lead.requested_at) THEN
        RAISE EXCEPTION 'lead_notification_source_mismatch';
    END IF;
    IF TG_OP='INSERT' AND NEW.expanded_at IS NOT NULL THEN
        RAISE EXCEPTION 'lead_notification_source_mismatch';
    END IF;
    IF TG_OP='UPDATE' AND (
       NEW.lead_id IS DISTINCT FROM OLD.lead_id
       OR (OLD.expanded_at IS NOT NULL AND
           NEW.expanded_at IS DISTINCT FROM OLD.expanded_at)) THEN
        RAISE EXCEPTION 'lead_notification_source_mismatch';
    END IF;
    IF NEW.expanded_at IS NOT NULL AND (
       NEW.expanded_at < NEW.created_at OR NOT EXISTS (
           SELECT 1 FROM accompaniment_lead_deliveries
           WHERE lead_id=NEW.lead_id AND order_id=NEW.order_id)) THEN
        RAISE EXCEPTION 'lead_notification_source_mismatch';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER accompaniment_queue_proof
BEFORE INSERT OR UPDATE ON accompaniment_lead_outbox
FOR EACH ROW EXECUTE FUNCTION accompaniment_queue_source();

CREATE OR REPLACE FUNCTION accompaniment_delivery_scope() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
    IF TG_OP='UPDATE' AND
       (NEW.job_id,NEW.lead_id,NEW.order_id,NEW.recipient_id) IS DISTINCT FROM
       (OLD.job_id,OLD.lead_id,OLD.order_id,OLD.recipient_id) THEN
        RAISE EXCEPTION 'lead_delivery_scope_immutable';
    END IF;
    IF TG_OP='INSERT' AND (
       NEW.state <> 'ready' OR NEW.attempt_count <> 0
       OR NOT EXISTS (SELECT 1 FROM accompaniment_leads
           WHERE lead_id=NEW.lead_id AND order_id=NEW.order_id)
       OR NOT EXISTS (SELECT 1 FROM users
           WHERE user_id=NEW.recipient_id AND admin AND status='active')) THEN
        RAISE EXCEPTION 'lead_delivery_source_mismatch';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER accompaniment_delivery_proof
BEFORE INSERT OR UPDATE ON accompaniment_lead_deliveries
FOR EACH ROW EXECUTE FUNCTION accompaniment_delivery_scope();
"""
