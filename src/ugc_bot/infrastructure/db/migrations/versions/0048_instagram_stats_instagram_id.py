"""Add instagram_id column to instagram_stats."""

import sqlalchemy as sa
from alembic import op

revision = "0048_instagram_stats_instagram_id"
down_revision = "0047_instagram_stats_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add instagram_id column (Instagram user id from API response)."""
    op.add_column(
        "instagram_stats",
        sa.Column("instagram_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    """Remove instagram_id column."""
    op.drop_column("instagram_stats", "instagram_id")
