"""Add telegram column to users for storing Telegram alias (admin only)."""

import sqlalchemy as sa
from alembic import op

revision = "0017_user_telegram"
down_revision = "0016_allow_zero_price_for_barter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add telegram column to users table."""
    op.add_column(
        "users",
        sa.Column("telegram", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Remove telegram column from users table."""
    op.drop_column("users", "telegram")
