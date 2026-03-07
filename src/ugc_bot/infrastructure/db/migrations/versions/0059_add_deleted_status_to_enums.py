"""Add 'deleted' value to status enums for soft delete in admin."""

from alembic import op

revision = "0059_add_deleted_status_to_enums"
down_revision = "0058_drop_blogger_profile_instagram_media_follows_biography"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add 'deleted' to status enums for soft delete."""
    op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'deleted'")
    op.execute("ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'deleted'")
    op.execute(
        "ALTER TYPE interaction_status ADD VALUE IF NOT EXISTS 'deleted'"
    )
    op.execute("ALTER TYPE complaint_status ADD VALUE IF NOT EXISTS 'deleted'")
    op.execute(
        "ALTER TYPE payout_request_status ADD VALUE IF NOT EXISTS 'deleted'"
    )


def downgrade() -> None:
    """PostgreSQL does not support removing enum values. No-op."""
    pass
