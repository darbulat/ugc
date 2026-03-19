"""Add phone column to blogger_profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0077_add_phone_to_blogger_profiles"
down_revision = "0076_add_ugc_video_url_offer_dispatches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable phone text column to blogger_profiles."""
    op.add_column(
        "blogger_profiles",
        sa.Column("phone", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Remove phone column from blogger_profiles."""
    op.drop_column("blogger_profiles", "phone")
