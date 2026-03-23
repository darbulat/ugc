"""Add bot_blocked value to user_status enum.

Revision ID: 0082
Revises: 0081
"""

from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'bot_blocked'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    # To roll back: recreate the enum without 'bot_blocked' and migrate the column.
    pass
