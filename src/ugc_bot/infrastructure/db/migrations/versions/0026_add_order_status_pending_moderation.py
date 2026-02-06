"""Add pending_moderation to order_status enum."""

from alembic import op

revision = "0026_add_order_status_pending_moderation"
down_revision = "0025_add_order_product_photo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add pending_moderation value to order_status enum."""
    op.execute(
        "ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'pending_moderation'"
    )


def downgrade() -> None:
    """PostgreSQL does not support removing enum values.

    Downgrade is a no-op. Existing rows with pending_moderation would need
    to be migrated manually before removing the value.
    """
    pass
