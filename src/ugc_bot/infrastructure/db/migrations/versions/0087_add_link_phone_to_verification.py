"""Add link_phone to instagram_verification_codes.

Revision ID: 0087
Revises: 0086
"""

import sqlalchemy as sa
from alembic import op

revision = "0087"
down_revision = "0086"


def upgrade() -> None:
    op.add_column(
        "instagram_verification_codes",
        sa.Column("link_phone", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instagram_verification_codes", "link_phone")
