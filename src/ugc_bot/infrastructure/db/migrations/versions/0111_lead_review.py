"""Immutable versioned accompaniment lead decisions."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.partner_admin_schema import (
    install_immutability,
    migration_metadata,
    review_table,
)

revision = "0111_lead_review"
down_revision = "0110_commercial_completion"
branch_labels = None
depends_on = None


def upgrade():
    table = review_table(migration_metadata())
    connection = op.get_bind()
    connection.execute(sa.schema.CreateTable(table))
    install_immutability(connection, table)


def downgrade():
    table = review_table(migration_metadata())
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE accompaniment_lead_reviews IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.scalar(sa.select(sa.func.count()).select_from(table)):
        raise RuntimeError("lead_review_history_exists")
    connection.execute(sa.schema.DropTable(table))
    connection.exec_driver_sql("DROP FUNCTION partner_admin_deny_mutation()")
