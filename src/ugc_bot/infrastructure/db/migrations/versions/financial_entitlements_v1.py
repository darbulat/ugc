"""Persist immutable client capture assessments in the journal transaction."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.entitlement_models import TABLES

revision = "financial_entitlements_v1"
down_revision = "financial_notices_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in TABLES:
        table.create(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE financial_client_assessments IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.execute(
        sa.text("SELECT 1 FROM financial_client_assessments LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard existing client assessments")
    for table in reversed(TABLES):
        table.drop(connection)
    connection.execute(
        sa.text("DROP FUNCTION financial_entitlement_deny_mutation()")
    )
