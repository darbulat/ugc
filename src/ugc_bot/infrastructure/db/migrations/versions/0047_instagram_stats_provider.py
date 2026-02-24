"""Add provider (data source) column to instagram_stats."""

import sqlalchemy as sa
from alembic import op

revision = "0047_instagram_stats_provider"
down_revision = "0046_instagram_stats_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add provider column with default for existing rows."""
    op.add_column(
        "instagram_stats",
        sa.Column(
            "provider",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'rapid_api'"),
        ),
    )


def downgrade() -> None:
    """Remove provider column."""
    op.drop_column("instagram_stats", "provider")
