"""Add durable order dispatch control and delivery claims."""

import sqlalchemy as sa
from alembic import op

revision = "0131_dispatch_pause"
down_revision = "0130_complimentary_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_dispatch_controls",
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("run", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("audience_ready", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "order_dispatch_claims",
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey(
                "order_dispatch_controls.order_id", ondelete="CASCADE"
            ),
            primary_key=True,
        ),
        sa.Column(
            "blogger_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("run", sa.Integer(), nullable=False),
        sa.Column("rejected", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "LOCK TABLE order_dispatch_controls IN ACCESS EXCLUSIVE MODE"
    )
    if bind.exec_driver_sql(
        "SELECT 1 FROM order_dispatch_controls LIMIT 1"
    ).first():
        raise RuntimeError("Cannot discard dispatch history")
    op.drop_table("order_dispatch_claims")
    op.drop_table("order_dispatch_controls")
