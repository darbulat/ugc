"""Separate approved public offers from the private order brief."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0142_creator_offer_cards"
down_revision = "0141_browser_only_orders"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("creator_offer_card", JSONB()))
    op.add_column(
        "offer_channel_attribution",
        sa.Column("creator_card_message_id", sa.String(128)),
    )
    op.add_column(
        "offer_channel_attribution",
        sa.Column("creator_card_updated_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_column("offer_channel_attribution", "creator_card_updated_at")
    op.drop_column("offer_channel_attribution", "creator_card_message_id")
    op.drop_column("orders", "creator_offer_card")
