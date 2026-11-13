"""Persist Telegram order summaries and constrain automatic replacements."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.order_summary_models import summary_tables
from ugc_bot.infrastructure.db.replacement_schema import review_guard_sql

revision = "0132_telegram_order_summary"
down_revision = "0131_dispatch_pause"
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    for name, key in (
        ("orders", "order_id"),
        ("item_assignments", "assignment_id"),
    ):
        sa.Table(name, metadata, sa.Column(key, sa.Uuid(), primary_key=True))
    bind = op.get_bind()
    for table in summary_tables(metadata):
        table.create(bind)
    bind.exec_driver_sql(review_guard_sql(automatic=True))


def downgrade():
    bind = op.get_bind()
    bind.exec_driver_sql(
        "LOCK TABLE paid_replacement_decisions, telegram_order_exceptions, "
        "telegram_order_summaries IN ACCESS EXCLUSIVE MODE"
    )
    if bind.exec_driver_sql(
        "SELECT 1 FROM telegram_order_summaries UNION ALL "
        "SELECT 1 FROM telegram_order_exceptions LIMIT 1"
    ).first():
        raise RuntimeError("telegram_order_summary_history_exists")
    bind.exec_driver_sql(review_guard_sql())
    op.drop_table("telegram_order_summary_jobs")
    op.drop_table("telegram_order_exceptions")
    op.drop_table("telegram_order_summaries")
