"""Remove name column from advertiser_profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0018_remove_advertiser_profile_name"
down_revision = "0017_user_telegram"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove name column from advertiser_profiles."""
    op.drop_column("advertiser_profiles", "name")


def downgrade() -> None:
    """Restore name column to advertiser_profiles."""
    op.add_column(
        "advertiser_profiles",
        sa.Column("name", sa.String(), nullable=True),
    )
