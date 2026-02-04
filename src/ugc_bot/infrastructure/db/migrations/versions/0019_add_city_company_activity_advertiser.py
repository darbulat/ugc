"""Add city and company_activity to advertiser_profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0019_add_city_company_activity_advertiser"
down_revision = "0018_remove_advertiser_profile_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add city and company_activity columns to advertiser_profiles."""
    op.add_column(
        "advertiser_profiles",
        sa.Column("city", sa.String(), nullable=True),
    )
    op.add_column(
        "advertiser_profiles",
        sa.Column("company_activity", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Remove city and company_activity from advertiser_profiles."""
    op.drop_column("advertiser_profiles", "company_activity")
    op.drop_column("advertiser_profiles", "city")
