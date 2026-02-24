"""Add birth_date column to blogger_profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0049_blogger_profile_birth_date"
down_revision = "0048_instagram_stats_instagram_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add birth_date column to blogger_profiles."""
    op.add_column(
        "blogger_profiles",
        sa.Column("birth_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    """Remove birth_date from blogger_profiles."""
    op.drop_column("blogger_profiles", "birth_date")
