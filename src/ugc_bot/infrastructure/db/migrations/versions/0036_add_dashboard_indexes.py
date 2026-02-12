"""Add indexes for admin dashboard queries (created_at, status, paid_at)."""

from alembic import op

revision = "0036_add_dashboard_indexes"
down_revision = "0035_referral_pending_no_duplicate_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create indexes for dashboard-heavy filters and date ranges."""
    op.create_index(
        "ix_users_created_at",
        "users",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_orders_created_at",
        "orders",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_complaints_status",
        "complaints",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_payments_status",
        "payments",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_payments_paid_at",
        "payments",
        ["paid_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove dashboard indexes."""
    op.drop_index("ix_payments_paid_at", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_complaints_status", table_name="complaints")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_users_created_at", table_name="users")
