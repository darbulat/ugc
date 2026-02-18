"""Add offer_dispatch_limits table (singleton for admin min/max followers)."""

import sqlalchemy as sa
from alembic import op

revision = "0044_offer_dispatch_limits"
down_revision = "0043_add_created_at_updated_at_main_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create offer_dispatch_limits and insert default row."""
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


def downgrade() -> None:
    """Drop offer_dispatch_limits table."""
    op.drop_table("offer_dispatch_limits")
