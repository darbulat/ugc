"""Keep Telegram payment disabled for orders switched to browser checkout."""

from alembic import op
from sqlalchemy import select

from ugc_bot.infrastructure.db import models  # noqa: F401
from ugc_bot.infrastructure.db.browser_checkout_models import (
    BROWSER_ONLY_ORDERS,
)

revision = "0141_browser_only_orders"
down_revision = "0140_browser_checkout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    BROWSER_ONLY_ORDERS.create(connection)
    connection.exec_driver_sql(
        """
CREATE FUNCTION browser_only_guard_native_auth() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM orders WHERE order_id = NEW.order_id FOR UPDATE;
    IF EXISTS (SELECT 1 FROM browser_only_orders WHERE order_id = NEW.order_id)
    THEN
        RAISE EXCEPTION 'browser_payment_active' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER browser_only_native_authorization
    BEFORE INSERT ON checkout_authorizations FOR EACH ROW
    EXECUTE FUNCTION browser_only_guard_native_auth();
"""
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE browser_only_orders IN ACCESS EXCLUSIVE MODE"
    )
    if connection.execute(
        select(BROWSER_ONLY_ORDERS.c.order_id).limit(1)
    ).first():
        raise RuntimeError(
            "Cannot re-enable Telegram payments for switched orders"
        )
    connection.exec_driver_sql(
        """
DROP TRIGGER browser_only_native_authorization ON checkout_authorizations;
DROP FUNCTION browser_only_guard_native_auth();
"""
    )
    BROWSER_ONLY_ORDERS.drop(connection)
