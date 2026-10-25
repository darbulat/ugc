"""Reviewed reserve promotion and immutable contact disclosure history."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.replacement_schema import (
    authority_sql,
    immutability_sql,
    migration_metadata,
    replacement_tables,
)

revision = "0114_refund_replacements"
down_revision = "0113_campaign_analytics"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    tables = replacement_tables(migration_metadata())
    for table in tables.values():
        connection.execute(sa.schema.CreateTable(table))
        for index in table.indexes:
            connection.execute(sa.schema.CreateIndex(index))
    connection.exec_driver_sql(immutability_sql(tables.values()))
    connection.exec_driver_sql(authority_sql())


def downgrade():
    connection = op.get_bind()
    tables = replacement_tables(migration_metadata())
    for table in tables.values():
        connection.execute(
            sa.text(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
        )
        if connection.scalar(sa.select(sa.func.count()).select_from(table)):
            raise RuntimeError("replacement_history_exists")
    for table in reversed(tuple(tables.values())):
        connection.execute(sa.schema.DropTable(table))
    connection.exec_driver_sql("DROP FUNCTION paid_replacement_deny_mutation()")
    connection.exec_driver_sql("DROP FUNCTION paid_replacement_review_guard()")
    connection.exec_driver_sql(
        "DROP FUNCTION paid_replacement_allocation_guard()"
    )
