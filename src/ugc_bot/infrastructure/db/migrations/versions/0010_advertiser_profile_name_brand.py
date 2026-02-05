"""Add name and brand to advertiser_profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0010_advertiser_name_brand"
down_revision = "0009_blogger_city_barter_fmt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add name and brand columns to advertiser_profiles."""

    op.add_column(
        "advertiser_profiles",
        sa.Column("name", sa.String(), nullable=True),
    )
    op.add_column(
        "advertiser_profiles",
        sa.Column("brand", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Remove name and brand from advertiser_profiles."""

    op.drop_column("advertiser_profiles", "brand")
    op.drop_column("advertiser_profiles", "name")
