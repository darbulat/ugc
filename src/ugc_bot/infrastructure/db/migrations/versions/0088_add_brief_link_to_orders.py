"""Add brief_link to orders.

Revision ID: 0088
Revises: 0087
"""

import sqlalchemy as sa
from alembic import op

revision = "0088"
down_revision = "0087"


def upgrade() -> None:
    op.add_column("orders", sa.Column("brief_link", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "brief_link")
