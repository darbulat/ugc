"""Add max_chat_id column to users table.

Max API uses separate user_id and chat_id. user_id (stored in max_id)
identifies the user, chat_id (stored in max_chat_id) is needed to send
messages.

Revision ID: 0085
Revises: 0084
"""

import sqlalchemy as sa
from alembic import op

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("max_chat_id", sa.String, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "max_chat_id")
