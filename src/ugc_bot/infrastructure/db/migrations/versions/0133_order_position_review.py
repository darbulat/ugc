"""Add staff-only paid-position ownership and deadline alerts."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.order_review_models import order_review_tables

revision = "0133_order_position_review"
down_revision = "0132_telegram_order_summary"
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    for table, key in (
        ("orders", "order_id"),
        ("order_items", "paid_item_id"),
        ("users", "user_id"),
    ):
        sa.Table(table, metadata, sa.Column(key, sa.Uuid(), primary_key=True))
    for table in order_review_tables(metadata):
        table.create(op.get_bind())


def downgrade():
    bind = op.get_bind()
    bind.exec_driver_sql(
        "LOCK TABLE order_review_alerts, order_review_owners "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if bind.exec_driver_sql(
        "SELECT 1 FROM order_review_alerts UNION ALL "
        "SELECT 1 FROM order_review_owners LIMIT 1"
    ).first():
        raise RuntimeError("order_position_review_history_exists")
    op.drop_table("order_review_alerts")
    op.drop_table("order_review_owners")
