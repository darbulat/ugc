"""Add content_usage, deadlines, geography to orders."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0015_order_content_usage_deadlines_geography"
down_revision = "0014_extend_alembic_version_col"
branch_labels = None
depends_on = None


def _orders_has_column(connection: sa.engine.Connection, name: str) -> bool:
    """Return True if orders table has the given column."""
    insp = inspect(connection)
    columns = [c["name"] for c in insp.get_columns("orders")]
    return name in columns


def upgrade() -> None:
    """Add nullable columns for content usage, deadlines, geography."""
    conn = op.get_bind()
    if not _orders_has_column(conn, "content_usage"):
        op.add_column("orders", sa.Column("content_usage", sa.String(), nullable=True))
    if not _orders_has_column(conn, "deadlines"):
        op.add_column("orders", sa.Column("deadlines", sa.String(), nullable=True))
    if not _orders_has_column(conn, "geography"):
        op.add_column("orders", sa.Column("geography", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove content_usage, deadlines, geography columns."""
    conn = op.get_bind()
    if _orders_has_column(conn, "geography"):
        op.drop_column("orders", "geography")
    if _orders_has_column(conn, "deadlines"):
        op.drop_column("orders", "deadlines")
    if _orders_has_column(conn, "content_usage"):
        op.drop_column("orders", "content_usage")
