"""Add performance indexes for commonly queried columns."""

from alembic import op

revision = "0060_add_performance_indexes"
down_revision = "0059_add_deleted_status_to_enums"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create indexes for hot query paths identified in code review."""
    # orders.status — used in list_active() (full table scan without index)
    op.create_index(
        "ix_orders_status",
        "orders",
        ["status"],
        unique=False,
    )
    # interactions.status — used in list_by_status(), list_due_for_feedback()
    op.create_index(
        "ix_interactions_status",
        "interactions",
        ["status"],
        unique=False,
    )
    # interactions.(status, blogger_id) for unfulfilled interaction lookups
    op.create_index(
        "ix_interactions_status_blogger_id",
        "interactions",
        ["status", "blogger_id"],
        unique=False,
    )
    # interactions.next_check_at — used in list_due_for_feedback()
    op.create_index(
        "ix_interactions_next_check_at",
        "interactions",
        ["next_check_at"],
        unique=False,
    )
    # blogger_profiles.confirmed — used in list_confirmed_user_ids()
    op.create_index(
        "ix_blogger_profiles_confirmed",
        "blogger_profiles",
        ["confirmed"],
        unique=False,
    )
    # payout_requests.user_id — already created by 0032; use IF NOT EXISTS
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payout_requests_user_id"
        " ON payout_requests (user_id)"
    )


def downgrade() -> None:
    """Remove performance indexes."""
    # ix_payout_requests_user_id was created by 0032; 0032 downgrade drops it.
    op.drop_index(
        "ix_blogger_profiles_confirmed", table_name="blogger_profiles"
    )
    op.drop_index("ix_interactions_next_check_at", table_name="interactions")
    op.drop_index(
        "ix_interactions_status_blogger_id", table_name="interactions"
    )
    op.drop_index("ix_interactions_status", table_name="interactions")
    op.drop_index("ix_orders_status", table_name="orders")
