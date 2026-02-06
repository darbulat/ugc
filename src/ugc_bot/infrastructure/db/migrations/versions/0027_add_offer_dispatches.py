"""Add offer_dispatches table for tracking sent offers."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027_add_offer_dispatches"
down_revision = "0026_add_order_status_pending_moderation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create offer_dispatches table."""
    op.create_table(
        "offer_dispatches",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "blogger_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("order_id", "blogger_id"),
    )
    op.create_index(
        "ix_offer_dispatches_order_id",
        "offer_dispatches",
        ["order_id"],
    )


def downgrade() -> None:
    """Drop offer_dispatches table."""
    op.drop_index("ix_offer_dispatches_order_id", table_name="offer_dispatches")
    op.drop_table("offer_dispatches")
