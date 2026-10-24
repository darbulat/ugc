"""Durable checkout projections and immutable native evidence."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ugc_bot.infrastructure.db.base import Base

M = Base.metadata
J = sa.JSON().with_variant(JSONB(), "postgresql")


def identifier(name, *, primary=False, nullable=False):
    return sa.Column(
        name, UUID(as_uuid=True), primary_key=primary, nullable=nullable
    )


def timestamp(name, *, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


CHECKOUTS = sa.Table(
    "financial_checkouts",
    M,
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("orders.order_id"),
        primary_key=True,
    ),
    identifier("client_id"),
    sa.Column("account", sa.String(256), nullable=False),
    sa.Column("state", sa.String(30), nullable=False),
    identifier("attempt_id", nullable=True),
    sa.Column("invoice_url", sa.Text),
    timestamp("lease_until", nullable=True),
    identifier("authorization_id", nullable=True),
    sa.Column("version", sa.Integer, nullable=False),
)
REQUESTS = sa.Table(
    "checkout_requests",
    M,
    identifier("request_id", primary=True),
    identifier("client_id"),
    sa.Column("operation_key", sa.String(256), nullable=False),
    identifier("order_id"),
    sa.Column("payload_hash", sa.String(64), nullable=False),
    identifier("attempt_id", nullable=True),
    timestamp("created_at"),
    sa.UniqueConstraint(
        "client_id", "operation_key", name="uq_checkout_operation"
    ),
)
ATTEMPTS = sa.Table(
    "checkout_link_attempts",
    M,
    identifier("attempt_id", primary=True),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("financial_checkouts.order_id"),
        nullable=False,
    ),
    timestamp("created_at"),
    sa.Column("prepared", J, nullable=False),
)
RESULTS = sa.Table(
    "checkout_link_results",
    M,
    identifier("result_id", primary=True),
    sa.Column(
        "attempt_id",
        UUID(as_uuid=True),
        sa.ForeignKey("checkout_link_attempts.attempt_id"),
        nullable=False,
    ),
    timestamp("observed_at"),
    sa.Column("outcome", sa.String(20), nullable=False),
    sa.Column("invoice_url", sa.Text),
)
AUTHORIZATIONS = sa.Table(
    "checkout_authorizations",
    M,
    identifier("authorization_id", primary=True),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        sa.ForeignKey("financial_checkouts.order_id"),
        nullable=False,
    ),
    sa.Column("account", sa.String(256), nullable=False),
    sa.Column("query_id", sa.String(256), nullable=False),
    sa.Column("payer_external_id", sa.String(256), nullable=False),
    identifier("client_id"),
    sa.Column("amount_minor", sa.BigInteger, nullable=False),
    sa.Column("currency", sa.String(3), nullable=False),
    identifier("intent_id"),
    timestamp("approved_at"),
    sa.UniqueConstraint("account", "query_id", name="uq_checkout_native_query"),
)
REVIEWS = sa.Table(
    "checkout_authorization_reviews",
    M,
    identifier("review_id", primary=True),
    sa.Column(
        "authorization_id",
        UUID(as_uuid=True),
        sa.ForeignKey("checkout_authorizations.authorization_id"),
        nullable=False,
    ),
    identifier("actor_id"),
    sa.Column("operation_key", sa.String(256), nullable=False),
    sa.Column("expected_version", sa.Integer, nullable=False),
    sa.Column("payload_hash", sa.String(64), nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("evidence_reference", sa.Text, nullable=False),
    sa.Column("source", sa.String(40), nullable=False),
    timestamp("reviewed_at"),
    sa.UniqueConstraint(
        "actor_id", "operation_key", name="uq_checkout_review_operation"
    ),
)
INBOX = sa.Table(
    "checkout_paid_inbox",
    M,
    identifier("receipt_id", primary=True),
    sa.Column(
        "order_id",
        UUID(as_uuid=True),
        nullable=False,
    ),
    sa.Column("account", sa.String(256), nullable=False),
    sa.Column("source_key", sa.String(256), nullable=False),
    sa.Column("payload_hash", sa.String(64), nullable=False),
    sa.Column("receipt", J, nullable=False),
    timestamp("received_at"),
    sa.UniqueConstraint(
        "account", "source_key", name="uq_checkout_paid_source"
    ),
)
INBOX_STATE = sa.Table(
    "checkout_paid_processing",
    M,
    sa.Column(
        "receipt_id",
        UUID(as_uuid=True),
        sa.ForeignKey("checkout_paid_inbox.receipt_id"),
        primary_key=True,
    ),
    sa.Column("state", sa.String(30), nullable=False),
    timestamp("lease_until", nullable=True),
    sa.Column("attempts", sa.Integer, nullable=False),
    identifier("claim_id", nullable=True),
    sa.Column("error", sa.String(120)),
)
NOTICE_JOBS = sa.Table(
    "checkout_paid_notices",
    M,
    identifier("job_id", primary=True),
    sa.Column(
        "receipt_id",
        UUID(as_uuid=True),
        sa.ForeignKey("checkout_paid_inbox.receipt_id"),
        nullable=False,
    ),
    identifier("order_id"),
    identifier("recipient_id"),
    sa.Column("account", sa.String(256), nullable=False),
    sa.Column("kind", sa.String(20), nullable=False),
    sa.Column("state", sa.String(20), nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False),
    identifier("current_attempt_id", nullable=True),
    timestamp("lease_until", nullable=True),
    sa.UniqueConstraint(
        "order_id", "recipient_id", name="uq_checkout_paid_notice_recipient"
    ),
)
NOTICE_ATTEMPTS = sa.Table(
    "checkout_paid_notice_attempts",
    M,
    identifier("attempt_id", primary=True),
    sa.Column(
        "job_id",
        UUID(as_uuid=True),
        sa.ForeignKey("checkout_paid_notices.job_id"),
        nullable=False,
    ),
    timestamp("prepared_at"),
    timestamp("lease_until"),
    sa.Column("channel", sa.String(20), nullable=False),
    sa.Column("address", sa.String(256), nullable=False),
    sa.Column("text", sa.Text, nullable=False),
)
NOTICE_RESULTS = sa.Table(
    "checkout_paid_notice_results",
    M,
    identifier("result_id", primary=True),
    sa.Column(
        "attempt_id",
        UUID(as_uuid=True),
        sa.ForeignKey("checkout_paid_notice_attempts.attempt_id"),
        nullable=False,
    ),
    timestamp("observed_at"),
    sa.Column("outcome", sa.String(20), nullable=False),
    sa.Column("reference", sa.String(512)),
    sa.Column("applied", sa.Boolean, nullable=False),
)
TABLES = (
    CHECKOUTS,
    REQUESTS,
    ATTEMPTS,
    RESULTS,
    AUTHORIZATIONS,
    REVIEWS,
    INBOX,
    INBOX_STATE,
    NOTICE_JOBS,
    NOTICE_ATTEMPTS,
    NOTICE_RESULTS,
)
FACTS = (
    REQUESTS,
    ATTEMPTS,
    RESULTS,
    AUTHORIZATIONS,
    REVIEWS,
    INBOX,
    NOTICE_ATTEMPTS,
    NOTICE_RESULTS,
)
TRIGGER_SQL = (
    """
CREATE FUNCTION checkout_deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'checkout_evidence_immutable' USING ERRCODE='23514';
END $$;
"""
    + "\n".join(
        f"CREATE TRIGGER {t.name}_immutable "
        f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {t.name} "
        "FOR EACH STATEMENT EXECUTE FUNCTION checkout_deny_mutation();"
        for t in FACTS
    )
    + """
CREATE FUNCTION checkout_guard_authorization() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.authorization_id IS NOT NULL
 AND NEW.authorization_id IS DISTINCT FROM OLD.authorization_id
 AND NOT EXISTS (SELECT 1 FROM checkout_authorization_reviews r
                 WHERE r.authorization_id=OLD.authorization_id
                 AND r.expected_version=OLD.version)
 THEN RAISE EXCEPTION 'checkout_authorization_requires_review'; END IF;
 IF NEW.authorization_id IS NOT NULL AND NOT EXISTS
 (SELECT 1 FROM checkout_authorizations a
  WHERE a.authorization_id=NEW.authorization_id
  AND a.order_id=NEW.order_id AND a.account=NEW.account
  AND a.client_id=NEW.client_id)
 THEN RAISE EXCEPTION 'checkout_authorization_source_mismatch'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER checkout_authorization_guard BEFORE UPDATE ON financial_checkouts
FOR EACH ROW EXECUTE FUNCTION checkout_guard_authorization();
"""
)
