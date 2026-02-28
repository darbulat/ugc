"""PostGIS: region, location_geometry (blogger_profiles, orders); radius_km."""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision = "0053_postgis_geometry_region_radius"
down_revision = "0052_orders_price_filter_delta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.add_column(
        "blogger_profiles",
        sa.Column("region", sa.String(), nullable=True),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "location_geometry",
            Geometry(geometry_type="MULTIPOINT", srid=4326),
            nullable=True,
        ),
    )

    op.add_column(
        "orders",
        sa.Column(
            "location_geometry",
            Geometry(geometry_type="POINT", srid=4326),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("radius_km", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "radius_km")
    op.drop_column("orders", "location_geometry")
    op.drop_column("blogger_profiles", "location_geometry")
    op.drop_column("blogger_profiles", "region")
    op.execute("DROP EXTENSION IF EXISTS postgis")
