"""Durable invoice attempts, one-charge authority and paid native inbox."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.checkout_models import TABLES, TRIGGER_SQL

revision = "checkout_v1"
down_revision = "financial_payout_v1"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    for table in TABLES:
        connection.execute(sa.schema.CreateTable(table))
    connection.exec_driver_sql(TRIGGER_SQL)


def downgrade():
    raise RuntimeError(
        "Cannot discard checkout and authenticated payment evidence"
    )
