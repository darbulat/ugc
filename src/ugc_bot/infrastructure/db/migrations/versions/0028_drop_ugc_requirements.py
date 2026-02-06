"""Drop ugc_requirements column from orders table."""

import sqlalchemy as sa
from alembic import op

revision = "0028_drop_ugc_requirements"
down_revision = "0027_add_offer_dispatches"
branch_labels = None
depends_on = None


def _orders_has_column(connection: sa.engine.Connection, name: str) -> bool:
    """Return True if orders table has the given column."""
    insp = sa.inspect(connection)
    columns = [c["name"] for c in insp.get_columns("orders")]
    return name in columns


def upgrade() -> None:
    """Drop ugc_requirements column from orders."""
    conn = op.get_bind()
    if _orders_has_column(conn, "ugc_requirements"):
        op.drop_column("orders", "ugc_requirements")


def downgrade() -> None:
    """Restore ugc_requirements column to orders."""
    conn = op.get_bind()
    if not _orders_has_column(conn, "ugc_requirements"):
        op.add_column(
            "orders",
            sa.Column("ugc_requirements", sa.Text(), nullable=True),
        )
