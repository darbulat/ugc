"""Add price_filter_delta to orders for price range filter."""

import sqlalchemy as sa
from alembic import op

revision = "0052_orders_price_filter_delta"
down_revision = "0051_orders_filter_by_price_placement_barter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add price_filter_delta column to orders."""
    op.add_column(
        "orders",
        sa.Column("price_filter_delta", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    """Remove price_filter_delta from orders."""
    op.drop_column("orders", "price_filter_delta")
