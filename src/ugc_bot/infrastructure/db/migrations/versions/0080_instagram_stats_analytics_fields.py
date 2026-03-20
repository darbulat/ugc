"""Add analytics fields to instagram_stats table."""

import sqlalchemy as sa
from alembic import op

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "instagram_stats",
        sa.Column("full_name", sa.String(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("is_professional_account", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("is_business_account", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("category_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("external_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("avg_likes", sa.Float(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("avg_comments", sa.Float(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("avg_video_views", sa.Float(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("engagement_rate", sa.Float(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("posting_frequency_days", sa.Float(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("total_video_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("total_photo_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("video_ratio", sa.Float(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("followers_to_follows_ratio", sa.Float(), nullable=True),
    )
    op.add_column(
        "instagram_stats",
        sa.Column("comments_to_likes_ratio", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instagram_stats", "comments_to_likes_ratio")
    op.drop_column("instagram_stats", "followers_to_follows_ratio")
    op.drop_column("instagram_stats", "video_ratio")
    op.drop_column("instagram_stats", "total_photo_count")
    op.drop_column("instagram_stats", "total_video_count")
    op.drop_column("instagram_stats", "posting_frequency_days")
    op.drop_column("instagram_stats", "engagement_rate")
    op.drop_column("instagram_stats", "avg_video_views")
    op.drop_column("instagram_stats", "avg_comments")
    op.drop_column("instagram_stats", "avg_likes")
    op.drop_column("instagram_stats", "external_url")
    op.drop_column("instagram_stats", "category_name")
    op.drop_column("instagram_stats", "is_business_account")
    op.drop_column("instagram_stats", "is_professional_account")
    op.drop_column("instagram_stats", "full_name")
