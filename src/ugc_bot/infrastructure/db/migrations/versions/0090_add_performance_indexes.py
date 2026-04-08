"""Add performance indexes for frequently queried columns.

Revision ID: 0090
Revises: 0089
"""

from alembic import op

revision = "0090"
down_revision = "0089"


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_status ON orders (status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_advertiser_id "
        "ON orders (advertiser_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_interactions_status_next_check_at "
        "ON interactions (status, next_check_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_blogger_profiles_confirmed "
        "ON blogger_profiles (confirmed) WHERE confirmed = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_blogger_profiles_confirmed")
    op.execute("DROP INDEX IF EXISTS ix_interactions_status_next_check_at")
    op.execute("DROP INDEX IF EXISTS ix_orders_advertiser_id")
    op.execute("DROP INDEX IF EXISTS ix_orders_status")
