"""Immutable own-network campaign lifecycle, delivery and responses."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.campaign_runtime_schema import (
    immutability_sql,
    runtime_tables,
)

revision = "00f0_campaign_runtime"
down_revision = "financial_refund_approvals_a1"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    owned = runtime_tables(sa.MetaData())
    for table in owned:
        connection.execute(sa.schema.CreateTable(table))
        for index in table.indexes:
            connection.execute(sa.schema.CreateIndex(index))
    connection.exec_driver_sql(immutability_sql(owned))


def downgrade():
    connection = op.get_bind()
    owned = runtime_tables(sa.MetaData())
    for table in owned:
        connection.execute(
            sa.text(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
        )
        if connection.scalar(sa.select(sa.func.count()).select_from(table)):
            raise RuntimeError("campaign_runtime_history_exists")
    for table in reversed(owned):
        connection.execute(sa.schema.DropTable(table))
    connection.exec_driver_sql("DROP FUNCTION campaign_runtime_deny_mutation()")
