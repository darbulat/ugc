"""Persist leases, immutable attempts with native actions and real outcomes."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.notice_delivery_models import TABLES

revision = "financial_notices_v1"
down_revision = "financial_lifecycle_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in TABLES:
        table.create(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    names = ", ".join(table.name for table in TABLES)
    connection.execute(sa.text(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE"))
    for table in TABLES:
        if connection.execute(
            sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")
        ).first():
            raise RuntimeError(
                "Cannot discard existing notice delivery history"
            )
    for table in reversed(TABLES):
        table.drop(connection)
    connection.execute(sa.text("DROP FUNCTION notice_check_attempt_proof()"))
    connection.execute(sa.text("DROP FUNCTION notice_deny_fact_mutation()"))
