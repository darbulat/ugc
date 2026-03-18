"""Add ugc_video_url column to offer_dispatches."""

import sqlalchemy as sa
from alembic import op

revision = "0076_add_ugc_video_url_offer_dispatches"
down_revision = "0075_drop_countries_locale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable ugc_video_url text column to offer_dispatches."""
    op.add_column(
        "offer_dispatches",
        sa.Column("ugc_video_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove ugc_video_url column from offer_dispatches."""
    op.drop_column("offer_dispatches", "ugc_video_url")
