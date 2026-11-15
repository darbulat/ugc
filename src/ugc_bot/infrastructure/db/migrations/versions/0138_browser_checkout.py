"""Reserve one browser invoice and admit verified YooKassa payments."""

from importlib import import_module

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db import models  # noqa: F401
from ugc_bot.infrastructure.db.browser_checkout_models import (
    BROWSER_ATTEMPTS,
    GUARD_SQL,
)

revision = "0138_browser_checkout"
down_revision = "0137_social_prompt_preference"
branch_labels = None
depends_on = None

_PROOF_START = " OR capture.payload->'capture' IS DISTINCT FROM"
_PROOF_END = " OR (capture.payload#>>'{capture,captured_at}')::timestamptz"
_BROWSER_CHECK = """ OR (CASE payment.provider WHEN 'yookassa_browser' THEN
 (capture.payload->'capture' IS DISTINCT FROM expected||jsonb_build_object(
 'external_id',payment.external_id,
 'browser_invoice_id',capture.payload#>>'{capture,browser_invoice_id}',
 'captured_at',capture.payload#>>'{capture,captured_at}',
 'captured_at_source','yookassa.payment.captured_at')
 OR NOT EXISTS (
 SELECT 1 FROM browser_checkout_attempts b
 WHERE b.order_id=request.order_id AND b.client_id=request.client_id
 AND b.state='paid'
 AND b.shop_id=invoice.payload->>'account' AND b.payment_id=payment.external_id
 AND b.invoice_id=capture.payload#>>'{capture,browser_invoice_id}'
 AND b.amount_minor=payment.captured_minor AND b.captured_at=payment.paid_at
 ))
 ELSE (__NATIVE_PROOF__) END)"""


def _authority_sql(browser: bool) -> str:
    public_scope = import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0127_public_policy_scope"
    )
    source = public_scope._authority_sql(public=True)
    if browser:
        start, end = source.index(_PROOF_START), source.index(_PROOF_END)
        proof = source[start:end].strip().removeprefix("OR ")
        source = (
            source[:start]
            + _BROWSER_CHECK.replace("__NATIVE_PROOF__", proof)
            + "\n"
            + source[end:]
        )
        source = source.replace(
            "'provider','yookassa_telegram'", "'provider',payment.provider"
        )
        source = source.replace(
            "payment.provider IS DISTINCT FROM 'yookassa_telegram'",
            "(payment.provider IS NULL OR payment.provider NOT IN "
            "('yookassa_telegram','yookassa_browser'))",
        )
    return source


def upgrade() -> None:
    connection = op.get_bind()
    BROWSER_ATTEMPTS.create(connection)
    connection.exec_driver_sql(GUARD_SQL)
    connection.exec_driver_sql(_authority_sql(True))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("LOCK TABLE browser_checkout_attempts IN ACCESS EXCLUSIVE MODE")
    )
    if connection.execute(
        sa.select(BROWSER_ATTEMPTS.c.attempt_id).limit(1)
    ).first():
        raise RuntimeError("Cannot discard browser payment history")
    connection.exec_driver_sql(_authority_sql(False))
    connection.exec_driver_sql(
        """
DROP TRIGGER browser_checkout_order_guard ON orders;
DROP TRIGGER browser_checkout_native_authorization ON checkout_authorizations;
DROP FUNCTION browser_checkout_guard_order();
DROP FUNCTION browser_checkout_guard_native_auth();
"""
    )
    BROWSER_ATTEMPTS.drop(connection)
