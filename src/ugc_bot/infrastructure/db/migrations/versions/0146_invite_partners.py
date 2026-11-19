"""Keep manual invitation partners separate from working managers."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.invite_partner_models import partner_table
from ugc_bot.infrastructure.db.partner_admin_schema import install_immutability

revision = "0146_invite_partners"
down_revision = "0145_instagram_profiles"
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    for table, column in (
        ("users", "user_id"),
        ("order_creator_invites", "id"),
    ):
        sa.Table(
            table, metadata, sa.Column(column, sa.Uuid(), primary_key=True)
        )
    table = partner_table(metadata)
    table.create(op.get_bind())
    install_immutability(op.get_bind(), table)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM order_creator_invite_partners) THEN
        RAISE EXCEPTION 'invite_partner_history_exists';
      END IF;
    END $$;""")
    op.drop_table("order_creator_invite_partners")
