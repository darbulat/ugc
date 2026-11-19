"""Track Instagram availability without replacing ownership evidence."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.instagram_maintenance_models import (
    maintenance_tables,
)

revision = "0145_instagram_profiles"
down_revision = "0144_manual_creator_transfers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata = sa.MetaData()
    for name, column in (("users", "user_id"), ("orders", "order_id")):
        sa.Table(name, metadata, sa.Column(column, sa.Uuid(), primary_key=True))
    for table in maintenance_tables(metadata):
        table.create(op.get_bind(), checkfirst=False)
    op.execute("""CREATE FUNCTION instagram_observation_immutable()
      RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'instagram_observation_history_required';
      END $$;
      CREATE TRIGGER instagram_observation_immutable
      BEFORE UPDATE OR DELETE ON instagram_profile_observations
      FOR EACH ROW EXECUTE FUNCTION instagram_observation_immutable();""")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM instagram_profile_observations)
        OR EXISTS (SELECT 1 FROM instagram_profile_notices)
        OR EXISTS (SELECT 1 FROM instagram_profile_health) THEN
        RAISE EXCEPTION 'instagram_maintenance_history_required';
      END IF;
    END $$;""")
    for name in (
        "instagram_profile_notices",
        "instagram_profile_observations",
        "instagram_profile_health",
    ):
        op.drop_table(name)
    op.execute("DROP FUNCTION instagram_observation_immutable()")
