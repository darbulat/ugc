"""Add index for list_confirmed_with_instagram_id query on blogger_profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0042_blogger_profiles_instagram_stats_index"
down_revision = "0041_blogger_profile_instagram_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Partial index for list_confirmed_with_instagram_id query."""
    where_clause = (
        "confirmed = true AND instagram_user_id IS NOT NULL "
        "AND instagram_user_id != ''"
    )
    op.create_index(
        "ix_blogger_profiles_confirmed_ig_stats_fetched",
        "blogger_profiles",
        ["instagram_stats_fetched_at", "user_id"],
        unique=False,
        postgresql_where=sa.text(where_clause),
        postgresql_ops={"instagram_stats_fetched_at": "ASC NULLS FIRST"},
    )


def downgrade() -> None:
    """Drop partial index for Instagram stats update query."""
    op.drop_index(
        "ix_blogger_profiles_confirmed_ig_stats_fetched",
        table_name="blogger_profiles",
    )
