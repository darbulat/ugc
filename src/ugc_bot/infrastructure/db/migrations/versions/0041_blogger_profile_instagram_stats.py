"""Add Instagram stats fields to blogger_profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0041_blogger_profile_instagram_stats"
down_revision = "0040_offer_dispatches_replace_order_responses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add instagram_user_id and stats columns to blogger_profiles."""
    op.add_column(
        "blogger_profiles",
        sa.Column("instagram_user_id", sa.String(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("instagram_followers_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("instagram_media_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("instagram_follows_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("instagram_biography", sa.Text(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("instagram_username", sa.String(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "instagram_stats_fetched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove Instagram stats columns from blogger_profiles."""
    op.drop_column("blogger_profiles", "instagram_stats_fetched_at")
    op.drop_column("blogger_profiles", "instagram_username")
    op.drop_column("blogger_profiles", "instagram_biography")
    op.drop_column("blogger_profiles", "instagram_follows_count")
    op.drop_column("blogger_profiles", "instagram_media_count")
    op.drop_column("blogger_profiles", "instagram_followers_count")
    op.drop_column("blogger_profiles", "instagram_user_id")
