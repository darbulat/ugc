"""Add order creator filter flags: price, placement, barter."""

import sqlalchemy as sa
from alembic import op

revision = "0051_orders_filter_by_price_placement_barter"
down_revision = "0050_orders_age_publications_gender"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add boolean filter columns to orders."""
    op.add_column(
        "orders",
        sa.Column(
            "filter_by_price",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "filter_by_placement",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "filter_by_barter",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    """Remove filter columns from orders."""
    op.drop_column("orders", "filter_by_barter")
    op.drop_column("orders", "filter_by_placement")
    op.drop_column("orders", "filter_by_price")
