"""Add support_messages table for helpdesk forwarding.

Revision ID: 0088
Revises: 0087
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0088"
down_revision = "0087"


def upgrade() -> None:
    op.create_table(
        "support_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column("user_chat_id", sa.String(255), nullable=False),
        sa.Column("support_chat_message_id", sa.BigInteger, nullable=False),
        sa.Column("user_text", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_support_messages_user_chat_id",
        "support_messages",
        ["user_chat_id"],
    )
    op.create_index(
        "ix_support_messages_support_chat_message_id",
        "support_messages",
        ["support_chat_message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("support_messages")
