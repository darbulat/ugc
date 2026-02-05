"""Rename contacts_sent_at to completed_at in orders table."""

from alembic import op

revision = "0020_rename_contacts_sent_at_to_completed_at"
down_revision = "0019_add_city_company_activity_advertiser"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rename contacts_sent_at to completed_at."""
    op.execute(
        "ALTER TABLE orders RENAME COLUMN contacts_sent_at TO completed_at"
    )


def downgrade() -> None:
    """Rename completed_at back to contacts_sent_at."""
    op.execute(
        "ALTER TABLE orders RENAME COLUMN completed_at TO contacts_sent_at"
    )
