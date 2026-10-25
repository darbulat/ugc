"""Immutable actor and reason for explicit referral attachment corrections."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.partner_admin_schema import (
    binding_table,
    install_immutability,
    migration_metadata,
)

revision = "0112_referral_binding_audit"
down_revision = "0111_lead_review"
branch_labels = None
depends_on = None


def upgrade():
    table = binding_table(migration_metadata())
    connection = op.get_bind()
    connection.execute(sa.schema.CreateTable(table))
    install_immutability(connection, table)


def downgrade():
    table = binding_table(migration_metadata())
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE referral_binding_corrections IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.scalar(sa.select(sa.func.count()).select_from(table)):
        raise RuntimeError("referral_correction_history_exists")
    connection.execute(sa.schema.DropTable(table))
