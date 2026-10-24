"""Append-only bounded correction facts, no active refund producer."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.correction_schema import (
    correction_tables,
    correction_trigger_sql,
)

revision = "financial_corrections_a1"
down_revision = "campaign_drafts_v1"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    for name, key in (
        ("users", "user_id"),
        ("orders", "order_id"),
        ("outbox_events", "event_id"),
        ("payments", "payment_id"),
        ("order_items", "paid_item_id"),
        ("financial_obligations", "id"),
        ("rate_snapshots", "id"),
        ("financial_movements", "id"),
        ("financial_audit_events", "id"),
    ):
        sa.Table(name, metadata, sa.Column(key, UUID, primary_key=True))
    sa.Table(
        "payment_item_allocations",
        metadata,
        sa.Column("allocation_key", sa.Text, primary_key=True),
    )
    return correction_tables(metadata)


def upgrade():
    connection = op.get_bind()
    owned = tables()
    for table in owned.values():
        connection.execute(sa.schema.CreateTable(table))
    connection.exec_driver_sql(correction_trigger_sql(owned))


def downgrade():
    connection = op.get_bind()
    owned = tables()
    for table in owned.values():
        connection.execute(
            sa.text(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
        )
    if any(
        connection.execute(sa.select(table).limit(1)).first()
        for table in owned.values()
    ):
        raise RuntimeError("Cannot discard immutable correction history")
    for table in reversed(tuple(owned.values())):
        connection.execute(sa.schema.DropTable(table))
    connection.execute(sa.text("DROP FUNCTION correction_check_application()"))
    connection.execute(sa.text("DROP FUNCTION correction_deny_mutation()"))
