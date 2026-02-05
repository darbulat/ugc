"""Add barter description to orders."""

import sqlalchemy as sa
from alembic import op

revision = "0003_add_barter_description"
down_revision = "0002_add_user_status_new"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema."""

    op.add_column(
        "orders", sa.Column("barter_description", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade database schema."""

    op.drop_column("orders", "barter_description")
