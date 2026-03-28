"""Add linking fields to instagram_verification_codes.

Revision ID: 0086
Revises: 0085
"""

import sqlalchemy as sa
from alembic import op

revision = "0086"
down_revision = "0085"


def upgrade() -> None:
    op.add_column(
        "instagram_verification_codes",
        sa.Column("link_max_id", sa.String(), nullable=True),
    )
    op.add_column(
        "instagram_verification_codes",
        sa.Column("link_max_chat_id", sa.String(), nullable=True),
    )
    op.add_column(
        "instagram_verification_codes",
        sa.Column("link_username", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instagram_verification_codes", "link_username")
    op.drop_column("instagram_verification_codes", "link_max_chat_id")
    op.drop_column("instagram_verification_codes", "link_max_id")
