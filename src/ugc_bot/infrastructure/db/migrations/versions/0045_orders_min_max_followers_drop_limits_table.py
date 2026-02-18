"""Add min_followers/max_followers to orders; drop offer_dispatch_limits."""

import sqlalchemy as sa
from alembic import op

revision = "0045_orders_min_max_followers_drop_limits_table"
down_revision = "0044_offer_dispatch_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add columns to orders and drop offer_dispatch_limits."""
    op.add_column(
        "orders",
        sa.Column("min_followers", sa.Integer(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("max_followers", sa.Integer(), nullable=True),
    )
    op.drop_table("offer_dispatch_limits")


def downgrade() -> None:
    """Recreate offer_dispatch_limits and remove columns from orders."""
    op.create_table(
        "offer_dispatch_limits",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("min_followers", sa.Integer(), nullable=False),
        sa.Column("max_followers", sa.Integer(), nullable=False),
        sa.Column("min_enabled", sa.Boolean(), nullable=False),
        sa.Column("max_enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO offer_dispatch_limits "
        "(id, min_followers, max_followers, min_enabled, max_enabled) "
        "VALUES (1, 1000, 100000, true, true)"
    )
    op.drop_column("orders", "max_followers")
    op.drop_column("orders", "min_followers")
