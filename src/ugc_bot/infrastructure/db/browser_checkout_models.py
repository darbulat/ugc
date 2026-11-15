"""Durable browser invoice reservation and verified provider outcome."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from ugc_bot.infrastructure.db.base import Base

ACTIVE_STATES = ("creating", "pending", "review")
ACTIVE_SQL = "state IN ('creating', 'pending', 'review')"

BROWSER_ATTEMPTS = sa.Table(
    "browser_checkout_attempts",
    Base.metadata,
    sa.Column("attempt_id", sa.Uuid(), primary_key=True),
    sa.Column(
        "order_id", sa.Uuid(), sa.ForeignKey("orders.order_id"), nullable=False
    ),
    sa.Column("client_id", sa.Uuid(), nullable=False),
    sa.Column("shop_id", sa.String(64), nullable=False),
    sa.Column("test_mode", sa.Boolean(), nullable=False),
    sa.Column("amount_minor", sa.BigInteger(), nullable=False),
    sa.Column("request", sa.JSON().with_variant(JSONB(), "postgresql")),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("invoice_id", sa.String(64)),
    sa.Column("invoice_url", sa.Text()),
    sa.Column("payment_id", sa.String(64)),
    sa.Column("captured_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("next_check_at", sa.DateTime(timezone=True)),
    sa.Column("claim_id", sa.Uuid()),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.CheckConstraint(
        "state IN ('creating', 'pending', 'review', "
        "'paid', 'canceled', 'failed')",
        name="ck_browser_checkout_state",
    ),
    sa.CheckConstraint("amount_minor > 0", name="ck_browser_checkout_amount"),
    sa.UniqueConstraint(
        "shop_id", "invoice_id", name="uq_browser_checkout_invoice"
    ),
    sa.UniqueConstraint(
        "shop_id", "payment_id", name="uq_browser_checkout_payment"
    ),
)
sa.Index(
    "uq_browser_checkout_active_order",
    BROWSER_ATTEMPTS.c.order_id,
    unique=True,
    postgresql_where=sa.text(ACTIVE_SQL),
    sqlite_where=sa.text(ACTIVE_SQL),
)
sa.Index("ix_browser_checkout_checks", BROWSER_ATTEMPTS.c.next_check_at)
sa.Index(
    "ix_browser_checkout_order",
    BROWSER_ATTEMPTS.c.order_id,
    BROWSER_ATTEMPTS.c.created_at,
)


def browser_payment_active(order_id):
    return sa.exists().where(
        BROWSER_ATTEMPTS.c.order_id == order_id,
        BROWSER_ATTEMPTS.c.state.in_(ACTIVE_STATES),
    )


def browser_capture_matches(order_id, identity, captured_at):
    return sa.exists().where(
        BROWSER_ATTEMPTS.c.order_id == order_id,
        BROWSER_ATTEMPTS.c.shop_id == identity.get("account"),
        BROWSER_ATTEMPTS.c.invoice_id == identity.get("browser_invoice_id"),
        BROWSER_ATTEMPTS.c.payment_id == identity.get("external_id"),
        BROWSER_ATTEMPTS.c.amount_minor == identity.get("amount_minor"),
        BROWSER_ATTEMPTS.c.captured_at == captured_at,
        BROWSER_ATTEMPTS.c.state == "paid",
    )


GUARD_SQL = """
CREATE FUNCTION browser_checkout_guard_native_auth() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 PERFORM 1 FROM orders WHERE order_id=NEW.order_id FOR UPDATE;
 IF EXISTS (SELECT 1 FROM browser_checkout_attempts
              WHERE order_id=NEW.order_id
              AND state IN ('creating','pending','review'))
 THEN RAISE EXCEPTION 'browser_payment_active' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER browser_checkout_native_authorization
 BEFORE INSERT ON checkout_authorizations FOR EACH ROW
 EXECUTE FUNCTION browser_checkout_guard_native_auth();

CREATE FUNCTION browser_checkout_guard_order() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.status, NEW.advertiser_id, NEW.complimentary,
     NEW.currency, NEW.financial_version)
    IS DISTINCT FROM
    (OLD.status, OLD.advertiser_id, OLD.complimentary,
     OLD.currency, OLD.financial_version)
 AND EXISTS (SELECT 1 FROM browser_checkout_attempts
              WHERE order_id=OLD.order_id
              AND state IN ('creating','pending','review'))
 THEN RAISE EXCEPTION 'browser_payment_active' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER browser_checkout_order_guard
 BEFORE UPDATE ON orders FOR EACH ROW
 EXECUTE FUNCTION browser_checkout_guard_order();

CREATE TRIGGER browser_checkout_paid_immutable
 BEFORE UPDATE OR DELETE ON browser_checkout_attempts FOR EACH ROW
 WHEN (OLD.state='paid') EXECUTE FUNCTION financial_deny_mutation();
"""
