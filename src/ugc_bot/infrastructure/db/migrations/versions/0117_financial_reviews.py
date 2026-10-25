"""Explicit review of issued income, preserving paid facts and debt history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.financial_review_schema import (
    financial_review_guards,
    financial_review_tables,
)

revision = "0117_financial_reviews"
down_revision = "0116_manual_grants"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    for name, key in (
        ("users", "user_id"),
        ("financial_obligations", "id"),
        ("order_items", "paid_item_id"),
        ("orders", "order_id"),
    ):
        sa.Table(name, metadata, sa.Column(key, UUID, primary_key=True))
    return financial_review_tables(metadata)


def upgrade():
    db = op.get_bind()
    owned = tables()
    for table in owned.values():
        db.execute(sa.schema.CreateTable(table))
    db.exec_driver_sql(financial_review_guards(owned))


def downgrade():
    db = op.get_bind()
    owned = tables()
    for table in owned.values():
        db.exec_driver_sql(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
    if any(db.execute(sa.select(t).limit(1)).first() for t in owned.values()):
        raise RuntimeError("financial_review_history_exists")
    db.exec_driver_sql(
        "DROP TRIGGER financial_review_movement_source ON financial_movements; "
        "DROP TRIGGER financial_review_recovery_source ON financial_movements;"
    )
    for table in reversed(tuple(owned.values())):
        db.execute(sa.schema.DropTable(table))
    db.exec_driver_sql(
        "DROP FUNCTION financial_review_check_movement(); "
        "DROP FUNCTION financial_review_check_recovery(); "
        "DROP FUNCTION financial_review_check_application(); "
        "DROP FUNCTION financial_review_before_resolution(); "
        "DROP FUNCTION financial_review_before_case(); "
        "DROP FUNCTION financial_review_restores("
        "jsonb,bigint,timestamptz,timestamptz); "
        "DROP FUNCTION financial_review_document(uuid);"
    )
