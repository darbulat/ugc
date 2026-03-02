"""Change orders.location_geometry from POINT to MULTIPOLYGON."""

from alembic import op

revision = "0055_orders_location_geometry_multipolygon"
down_revision = "0054_blogger_profile_country"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Alter location_geometry to MULTIPOLYGON; clear existing POINT data."""
    op.execute(
        """
        ALTER TABLE orders
        ALTER COLUMN location_geometry
        TYPE geometry(MULTIPOLYGON, 4326)
        USING NULL
        """
    )


def downgrade() -> None:
    """Revert location_geometry to POINT; MULTIPOLYGON data is cleared."""
    op.execute(
        """
        ALTER TABLE orders
        ALTER COLUMN location_geometry
        TYPE geometry(POINT, 4326)
        USING NULL
        """
    )
