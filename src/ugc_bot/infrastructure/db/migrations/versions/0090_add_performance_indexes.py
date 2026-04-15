"""Add performance indexes for frequently queried columns.

Revision ID: 0090
Revises: 0089
"""

from alembic import op

revision = "0090"
down_revision = "0089"


def upgrade() -> None:
    op.create_index(
        "ix_orders_status",
        "orders",
        ["status"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_orders_advertiser_id",
        "orders",
        ["advertiser_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_interactions_status_next_check_at",
        "interactions",
        ["status", "next_check_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_blogger_profiles_confirmed",
        "blogger_profiles",
        ["confirmed"],
        postgresql_where="confirmed = true",
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_blogger_profiles_confirmed",
        "blogger_profiles",
        if_exists=True,
    )
    op.drop_index(
        "ix_interactions_status_next_check_at",
        "interactions",
        if_exists=True,
    )
    op.drop_index("ix_orders_advertiser_id", "orders", if_exists=True)
    op.drop_index("ix_orders_status", "orders", if_exists=True)
