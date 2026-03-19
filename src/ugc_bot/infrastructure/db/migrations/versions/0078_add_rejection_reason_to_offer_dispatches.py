"""Add rejection_reason and desired_price to offer_dispatches."""

import sqlalchemy as sa
from alembic import op

revision = "0078_add_rejection_reason_to_offer_dispatches"
down_revision = "0077_add_phone_to_blogger_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable rejection_reason and desired_price columns."""
    op.add_column(
        "offer_dispatches",
        sa.Column("rejection_reason", sa.String(), nullable=True),
    )
    op.add_column(
        "offer_dispatches",
        sa.Column("desired_price", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    """Remove rejection_reason and desired_price columns."""
    op.drop_column("offer_dispatches", "desired_price")
    op.drop_column("offer_dispatches", "rejection_reason")
