"""Add product_photo_file_id to orders."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0025_add_order_product_photo"
down_revision = "0024_nps_user_id_comment"
branch_labels = None
depends_on = None


def _orders_has_column(connection: sa.engine.Connection, name: str) -> bool:
    """Return True if orders table has the given column."""
    insp = inspect(connection)
    columns = [c["name"] for c in insp.get_columns("orders")]
    return name in columns


def upgrade() -> None:
    """Add product_photo_file_id column to orders."""
    conn = op.get_bind()
    if not _orders_has_column(conn, "product_photo_file_id"):
        op.add_column(
            "orders",
            sa.Column("product_photo_file_id", sa.String(), nullable=True),
        )


def downgrade() -> None:
    """Remove product_photo_file_id column from orders."""
    conn = op.get_bind()
    if _orders_has_column(conn, "product_photo_file_id"):
        op.drop_column("orders", "product_photo_file_id")
