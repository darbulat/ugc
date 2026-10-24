"""Add immutable approval capsules without rewriting early refund history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.correction_approval_schema import (
    correction_approval_tables,
    correction_approval_trigger_sql,
)
from ugc_bot.infrastructure.db.correction_schema import GUARD_SQL

revision = "financial_refund_approvals_a1"
down_revision = "financial_corrections_a1"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    for name, key in (
        ("users", "user_id"),
        ("orders", "order_id"),
        ("payments", "payment_id"),
        ("outbox_events", "event_id"),
        ("financial_correction_commands", "command_id"),
        ("financial_correction_cases", "case_id"),
        ("financial_correction_requests", "request_id"),
        ("financial_refund_intents", "intent_id"),
        ("financial_refund_matches", "match_id"),
    ):
        sa.Table(name, metadata, sa.Column(key, UUID, primary_key=True))
    sa.Table(
        "financial_correction_events",
        metadata,
        sa.Column("case_id", UUID),
        sa.Column("version", sa.BigInteger),
    )
    return correction_approval_tables(metadata)


def upgrade():
    connection = op.get_bind()
    owned = tables()
    for table in owned.values():
        connection.execute(sa.schema.CreateTable(table))
    connection.exec_driver_sql(correction_approval_trigger_sql(owned))


def downgrade():
    connection = op.get_bind()
    owned = tables()
    # Lock and inspect first. A refusal must preserve the installed guard too.
    connection.execute(
        sa.text(
            "LOCK TABLE financial_refund_matches,financial_refund_applications,"
            "financial_refund_intent_approvals,"
            "financial_refund_match_approvals "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    if any(
        connection.execute(sa.select(t).limit(1)).first()
        for t in owned.values()
    ):
        raise RuntimeError("Cannot discard immutable refund approval history")
    connection.execute(
        sa.text(
            "DROP TRIGGER correction_approval_guard ON financial_refund_matches"
        )
    )
    for table in reversed(tuple(owned.values())):
        connection.execute(sa.schema.DropTable(table))
    connection.exec_driver_sql(GUARD_SQL)
    for function in (
        "correction_check_approval()",
        "correction_match_capsule(uuid,boolean)",
        "correction_validate_authority(jsonb)",
        "correction_approval_chain(uuid,bigint)",
        "correction_approval_row(jsonb,regclass)",
        "correction_approval_hash(jsonb)",
        "correction_approval_json(jsonb)",
    ):
        connection.execute(sa.text("DROP FUNCTION " + function))
