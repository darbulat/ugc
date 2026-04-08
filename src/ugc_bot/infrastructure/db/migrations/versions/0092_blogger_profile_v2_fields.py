"""Add v2 onboarding fields to blogger_profiles.

Adds: tax_status, price_with_publish, social links (telegram_channel_url,
vk_url, tiktok_url, youtube_url, likee_url), about, profile_photo_url,
gallery_photos (jsonb), video_links (jsonb).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0092_blogger_profile_v2_fields"
down_revision = "0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add v2 onboarding fields to blogger_profiles."""
    op.add_column(
        "blogger_profiles",
        sa.Column("tax_status", sa.String(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("price_with_publish", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("telegram_channel_url", sa.String(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("vk_url", sa.String(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("tiktok_url", sa.String(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("youtube_url", sa.String(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("likee_url", sa.String(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("about", sa.Text(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column("profile_photo_url", sa.String(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "gallery_photos",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "video_links",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Remove v2 onboarding fields from blogger_profiles."""
    op.drop_column("blogger_profiles", "video_links")
    op.drop_column("blogger_profiles", "gallery_photos")
    op.drop_column("blogger_profiles", "profile_photo_url")
    op.drop_column("blogger_profiles", "about")
    op.drop_column("blogger_profiles", "likee_url")
    op.drop_column("blogger_profiles", "youtube_url")
    op.drop_column("blogger_profiles", "tiktok_url")
    op.drop_column("blogger_profiles", "vk_url")
    op.drop_column("blogger_profiles", "telegram_channel_url")
    op.drop_column("blogger_profiles", "price_with_publish")
    op.drop_column("blogger_profiles", "tax_status")
