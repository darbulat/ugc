"""Store deduplicated creator offer interactions independently of responses."""

import sqlalchemy as sa
from alembic import op

revision = "0151_offer_card_actions"
down_revision = "0150_instagram_offer_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offer_card_action_events",
        sa.Column("order_id", sa.Uuid(), primary_key=True),
        sa.Column("blogger_id", sa.Uuid(), primary_key=True),
        sa.Column("channel", sa.String(8), primary_key=True),
        sa.Column("callback_digest", sa.String(64), primary_key=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ("order_id", "blogger_id"),
            ("offer_dispatches.order_id", "offer_dispatches.blogger_id"),
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("offer_card_action_events")
