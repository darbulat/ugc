"""Atomic requested accompaniment intake and durable notification intent."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.order_intake_models import TABLES, TRIGGER_SQL

revision = "accompaniment_leads_v1"
down_revision = "financial_work_entitlements_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for table in TABLES:
        connection.execute(sa.schema.CreateTable(table))
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            connection.execute(sa.schema.CreateIndex(index))
    connection.exec_driver_sql(TRIGGER_SQL)


def downgrade() -> None:
    raise RuntimeError("Cannot discard immutable order intake or lead history")
