"""Immutable campaign configuration and explicit per-inviter consent."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.campaign_models import TABLES

revision = "campaign_foundation_v1"
down_revision = "paid_selection_delivery_v1"
branch_labels = None
depends_on = None


def upgrade():
    for table in TABLES:
        table.create(op.get_bind())


def downgrade():
    db = op.get_bind()
    for table in TABLES:
        db.execute(sa.text(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE"))
    for table in TABLES:
        if db.execute(sa.select(table).limit(1)).first():
            raise RuntimeError("Cannot discard immutable campaign history")
    for table in reversed(TABLES):
        table.drop(db)
    db.execute(sa.text("DROP FUNCTION campaign_foundation_deny_mutation()"))
