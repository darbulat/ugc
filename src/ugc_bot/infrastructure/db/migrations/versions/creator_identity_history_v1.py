"""Observe canonical identities/direct bindings from this cutover onward."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.identity_history_models import TABLES
from ugc_bot.infrastructure.db.identity_history_schema import (
    CUTOVER_SQL,
    LOCK_SQL,
    TRIGGER_SQL,
)

revision = "creator_identity_history_v1"
down_revision = "financial_collaboration_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text(LOCK_SQL))
    for table in TABLES:
        connection.execute(sa.schema.CreateTable(table))
        for index in sorted(table.indexes, key=lambda index: index.name or ""):
            connection.execute(sa.schema.CreateIndex(index))
    connection.exec_driver_sql(TRIGGER_SQL)
    connection.exec_driver_sql(CUTOVER_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "Cannot discard immutable creator identity coverage/history"
    )
