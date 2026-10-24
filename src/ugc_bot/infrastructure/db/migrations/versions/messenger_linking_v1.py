"""Attach-only MAX/TG proof, immutable receipts and operational bounds."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.messenger_linking_schema import (
    immutability_sql,
    linking_tables,
)

revision = "messenger_linking_v1"
down_revision = "financial_payout_contracts_v1"
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("user_id", UUID, primary_key=True))
    tables = linking_tables(metadata)
    connection = op.get_bind()
    for table in tables.values():
        connection.execute(sa.schema.CreateTable(table))
        for index in table.indexes:
            connection.execute(sa.schema.CreateIndex(index))
    connection.exec_driver_sql(immutability_sql(tables))


def downgrade():
    raise RuntimeError("Cannot discard authenticated messenger binding facts")
