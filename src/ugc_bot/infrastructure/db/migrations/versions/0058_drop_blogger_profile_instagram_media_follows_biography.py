"""Drop instagram_media_count, instagram_follows_count, instagram_biography."""

import sqlalchemy as sa
from alembic import op

revision = "0058_drop_blogger_profile_instagram_media_follows_biography"
down_revision = "0057_add_bot_texts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop media_count, follows_count, biography from blogger_profiles."""
    op.drop_column("blogger_profiles", "instagram_biography")
    op.drop_column("blogger_profiles", "instagram_follows_count")
    op.drop_column("blogger_profiles", "instagram_media_count")


def downgrade() -> None:
    """Restore media_count, follows_count, biography to blogger_profiles."""
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
