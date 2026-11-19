"""Independent Discovery metrics, schedule and bounded request budget."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.instagram_discovery_models import (
    discovery_tables,
)

revision = "0147_instagram_discovery"
down_revision = "0146_invite_partners"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata = sa.MetaData()
    sa.Table(
        "users", metadata, sa.Column("user_id", sa.Uuid(), primary_key=True)
    )
    for table in discovery_tables(metadata):
        table.create(op.get_bind())


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM instagram_discovery_profiles)
        OR EXISTS (SELECT 1 FROM instagram_discovery_control) THEN
        RAISE EXCEPTION 'discovery_data_requires_explicit_retention_decision';
      END IF;
    END $$;""")
    op.drop_table("instagram_discovery_control")
    op.drop_table("instagram_discovery_profiles")
