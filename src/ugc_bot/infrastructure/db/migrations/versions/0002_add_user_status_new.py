"""Add NEW value to user_status enum."""

from __future__ import annotations

from alembic import op


revision = "0002_add_user_status_new"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema."""

    op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'new'")


def downgrade() -> None:
    """Downgrade database schema."""

    # Enum values cannot be removed safely; no-op. The type is dropped in 0001 downgrade.
    return None
