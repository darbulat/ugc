"""Add amount column to payout_requests."""

import sqlalchemy as sa
from alembic import op

revision = "0031_payout_request_amount"
down_revision = "0030_referral_per_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add amount column to payout_requests."""
    op.add_column(
        "payout_requests",
        sa.Column("amount", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    """Remove amount column from payout_requests."""
    op.drop_column("payout_requests", "amount")
