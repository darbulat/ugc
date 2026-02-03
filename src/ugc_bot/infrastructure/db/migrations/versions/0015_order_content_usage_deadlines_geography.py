"""Add content_usage, deadlines, geography to orders."""

import sqlalchemy as sa
from alembic import op

revision = "0015_order_content_usage_deadlines_geography"
down_revision = "0014_bloggers_needed_3_5_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable columns for content usage, deadlines, geography."""
    op.add_column("orders", sa.Column("content_usage", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("deadlines", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("geography", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove content_usage, deadlines, geography columns."""
    op.drop_column("orders", "geography")
    op.drop_column("orders", "deadlines")
    op.drop_column("orders", "content_usage")
