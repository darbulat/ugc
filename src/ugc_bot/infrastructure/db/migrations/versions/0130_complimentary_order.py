"""Record admin-approved complimentary orders without payment facts."""

import sqlalchemy as sa
from alembic import op

revision = "0130_complimentary_order"
down_revision = "0129_dispatch_city_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "complimentary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "dispatch_stopped",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("LOCK TABLE orders IN ACCESS EXCLUSIVE MODE")
    if bind.execute(
        sa.text("SELECT 1 FROM orders WHERE complimentary LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard complimentary order history")
    op.drop_column("orders", "dispatch_stopped")
    op.drop_column("orders", "complimentary")
