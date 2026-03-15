"""Add index on offer_dispatches.manager_id."""

from alembic import op

revision = "0069_add_index_offer_dispatches_manager_id"
down_revision = "0068_add_manager_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_offer_dispatches_manager_id",
        "offer_dispatches",
        ["manager_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_offer_dispatches_manager_id", "offer_dispatches")
