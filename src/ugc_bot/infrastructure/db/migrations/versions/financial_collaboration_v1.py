"""Persist creator-work lifecycle, immutable command facts and release times."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.collaboration_models import TABLES

revision = "financial_collaboration_v1"
down_revision = "creator_social_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for table in TABLES:
        table.create(connection)


def downgrade() -> None:
    connection = op.get_bind()
    names = ", ".join(table.name for table in TABLES)
    connection.execute(sa.text(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE"))
    for table in TABLES:
        if connection.execute(
            sa.text(f"SELECT 1 FROM {table.name} LIMIT 1")
        ).first():
            raise RuntimeError("Cannot discard existing collaboration history")
    for table in reversed(TABLES):
        table.drop(connection)
    connection.execute(
        sa.text("DROP FUNCTION collaboration_deny_fact_mutation()")
    )
