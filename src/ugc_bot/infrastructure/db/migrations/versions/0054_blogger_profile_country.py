"""Add country column to blogger_profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0054_blogger_profile_country"
down_revision = "0053_postgis_geometry_region_radius"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add country column with default 'russia'."""
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "country",
            sa.String(),
            nullable=False,
            server_default=sa.text("'russia'"),
        ),
    )


def downgrade() -> None:
    """Remove country column from blogger_profiles."""
    op.drop_column("blogger_profiles", "country")
