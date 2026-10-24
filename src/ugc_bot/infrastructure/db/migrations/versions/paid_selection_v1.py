"""Paid selection interest and durable delivery queue."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.paid_selection_models import TABLES

revision = "paid_selection_v1"
down_revision = "accompaniment_leads_v1"
branch_labels = None
depends_on = None


def upgrade():
    for table in TABLES:
        table.create(op.get_bind())


def downgrade():
    connection = op.get_bind()
    for table in TABLES:
        connection.execute(
            sa.text(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
        )
        if connection.execute(sa.select(table).limit(1)).first():
            raise RuntimeError("Cannot discard paid selection history")
    for table in reversed(TABLES):
        table.drop(connection)
    connection.execute(sa.text("DROP FUNCTION paid_selection_deny_mutation()"))
