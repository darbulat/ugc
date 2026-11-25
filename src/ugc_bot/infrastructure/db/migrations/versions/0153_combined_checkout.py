"""Allow a gross browser charge with a separately booked consultation."""

from importlib import import_module

import sqlalchemy as sa
from alembic import op

revision = "0153_combined_checkout"
down_revision = "0152_order_consultation"
branch_labels = None
depends_on = None

_BASE_PROOF = "b.amount_minor=payment.captured_minor"
_COMBINED_PROOF = """b.amount_minor=payment.captured_minor + CASE WHEN EXISTS (
    SELECT 1 FROM order_intake_receipts r
    JOIN order_consultations c USING (order_id)
    WHERE r.order_id=request.order_id AND r.client_id=request.client_id
      AND c.client_id=request.client_id
      AND r.result->'combined_checkout'='true'::jsonb
 ) THEN 500000 ELSE 0 END"""

_GUARDS = """
CREATE FUNCTION guard_checkout_package_amount()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected bigint;
BEGIN
 IF EXISTS (SELECT 1 FROM order_intake_receipts r WHERE r.order_id=NEW.order_id
     AND r.result->'combined_checkout'='true'::jsonb) THEN
   IF TG_TABLE_NAME='consultation_checkout_attempts' THEN
     RAISE EXCEPTION 'combined_checkout_requires_one_invoice'
       USING ERRCODE='23514';
   END IF;
   SELECT (p.amount*100)::bigint + CASE WHEN EXISTS (
       SELECT 1 FROM order_consultations c WHERE c.order_id=NEW.order_id
          AND c.client_id=NEW.client_id) THEN 500000 ELSE 0 END
      INTO expected FROM payments p JOIN orders o USING (order_id)
      WHERE p.order_id=NEW.order_id AND o.advertiser_id=NEW.client_id
         AND p.currency='RUB' AND p.status='pending';
   IF expected IS DISTINCT FROM NEW.amount_minor THEN
     RAISE EXCEPTION 'combined_checkout_amount_mismatch' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER browser_package_amount_guard
BEFORE INSERT ON browser_checkout_attempts
FOR EACH ROW EXECUTE FUNCTION guard_checkout_package_amount();
CREATE TRIGGER consultation_package_channel_guard
BEFORE INSERT ON consultation_checkout_attempts
FOR EACH ROW EXECUTE FUNCTION guard_checkout_package_amount();
"""


def _previous_authority() -> str:
    return import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0140_browser_checkout"
    )._authority_sql(True)


def upgrade() -> None:
    previous = _previous_authority()
    if previous.count(_BASE_PROOF) != 1:
        raise RuntimeError("Unexpected browser payment authority")
    connection = op.get_bind()
    connection.exec_driver_sql(previous.replace(_BASE_PROOF, _COMBINED_PROOF))
    connection.exec_driver_sql(_GUARDS)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("""
        SELECT 1 FROM order_intake_receipts
        WHERE result->'combined_checkout'='true'::jsonb LIMIT 1
    """)
    ).first():
        raise RuntimeError(
            "Cannot remove the combined checkout of existing orders"
        )
    connection.exec_driver_sql("""
        DROP TRIGGER browser_package_amount_guard
        ON browser_checkout_attempts;
        DROP TRIGGER consultation_package_channel_guard
        ON consultation_checkout_attempts;
        DROP FUNCTION guard_checkout_package_amount();
    """)
    connection.exec_driver_sql(_previous_authority())
