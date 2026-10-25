"""Explicit marketing evidence, event attribution and paid-pilot records."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.campaign_analytics_schema import (
    analytics_tables,
    immutability_sql,
)

revision = "0113_campaign_analytics"
down_revision = "0112_referral_binding_audit"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    tables = analytics_tables(sa.MetaData())
    for table in tables:
        connection.execute(sa.schema.CreateTable(table))
        for index in table.indexes:
            connection.execute(sa.schema.CreateIndex(index))
    connection.exec_driver_sql(immutability_sql(tables))


def downgrade():
    connection = op.get_bind()
    tables = analytics_tables(sa.MetaData())
    for table in tables:
        connection.execute(
            sa.text(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
        )
        if connection.scalar(sa.select(sa.func.count()).select_from(table)):
            raise RuntimeError("campaign_analytics_history_exists")
    for table in reversed(tables):
        connection.execute(sa.schema.DropTable(table))
    connection.exec_driver_sql(
        "DROP FUNCTION campaign_analytics_deny_mutation()"
    )
