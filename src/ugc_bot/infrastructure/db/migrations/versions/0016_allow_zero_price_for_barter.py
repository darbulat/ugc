"""Allow price >= 0 for barter orders (ugc_only with price 0)."""

from alembic import op

revision = "0016_allow_zero_price_for_barter"
down_revision = "0015_order_content_usage_deadlines_geography"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Change orders price constraint from price > 0 to price >= 0."""
    op.drop_constraint("orders_price_check", "orders", type_="check")
    op.create_check_constraint(
        "orders_price_check",
        "orders",
        "price >= 0",
    )


def downgrade() -> None:
    """Restore orders price constraint to price > 0."""
    op.drop_constraint("orders_price_check", "orders", type_="check")
    op.create_check_constraint(
        "orders_price_check",
        "orders",
        "price > 0",
    )
