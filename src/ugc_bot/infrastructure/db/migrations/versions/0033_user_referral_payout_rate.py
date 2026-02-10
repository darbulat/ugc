"""Add referral_payout_rate column to users (personalized referral %)."""

import sqlalchemy as sa
from alembic import op

revision = "0033_user_referral_payout_rate"
down_revision = "0032_payout_requests_index_and_one_per_day"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add referral_payout_rate column to users table."""
    op.add_column(
        "users",
        sa.Column(
            "referral_payout_rate",
            sa.Numeric(5, 4),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove referral_payout_rate column from users table."""
    op.drop_column("users", "referral_payout_rate")
