"""Add instagram_stats table for Rapid API profile statistics."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0046_instagram_stats_table"
down_revision = "0045_orders_min_max_followers_drop_limits_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create instagram_stats table with user_id PK and raw_response JSONB."""
    op.create_table(
        "instagram_stats",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("raw_response", JSONB(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("followers_count", sa.Integer(), nullable=True),
        sa.Column("follows_count", sa.Integer(), nullable=True),
        sa.Column("media_count", sa.Integer(), nullable=True),
        sa.Column("instagram_username", sa.String(), nullable=True),
        sa.Column("biography", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop instagram_stats table."""
    op.drop_table("instagram_stats")
