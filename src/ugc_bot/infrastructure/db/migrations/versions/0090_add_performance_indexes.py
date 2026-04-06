"""Add performance indexes for frequently queried columns.

Revision ID: 0090
Revises: 0089
"""

from alembic import op

revision = "0090"
down_revision = "0089"


def upgrade() -> None:
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_advertiser_id", "orders", ["advertiser_id"])
    op.create_index(
        "ix_interactions_status_next_check_at",
        "interactions",
        ["status", "next_check_at"],
    )
    op.create_index(
        "ix_blogger_profiles_confirmed",
        "blogger_profiles",
        ["confirmed"],
        postgresql_where="confirmed = true",
    )


def downgrade() -> None:
    op.drop_index("ix_blogger_profiles_confirmed", "blogger_profiles")
    op.drop_index("ix_interactions_status_next_check_at", "interactions")
    op.drop_index("ix_orders_advertiser_id", "orders")
    op.drop_index("ix_orders_status", "orders")
