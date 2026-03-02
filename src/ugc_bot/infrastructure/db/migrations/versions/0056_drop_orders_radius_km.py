"""Drop orders.radius_km column (unused in dispatch filtering)."""

import sqlalchemy as sa
from alembic import op

revision = "0056_drop_orders_radius_km"
down_revision = "0055_orders_location_geometry_multipolygon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove radius_km column from orders."""
    op.drop_column("orders", "radius_km", schema=None)


def downgrade() -> None:
    """Restore radius_km column on orders."""
    op.add_column(
        "orders",
        sa.Column("radius_km", sa.Numeric(10, 2), nullable=True),
        schema=None,
    )
