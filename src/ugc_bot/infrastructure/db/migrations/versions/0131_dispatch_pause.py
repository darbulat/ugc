"""Add durable order dispatch control and delivery claims."""

from alembic import op

from ugc_bot.infrastructure.db.dispatch_control import CLAIMS, CONTROLS

revision = "0131_dispatch_pause"
down_revision = "0130_complimentary_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    CONTROLS.create(op.get_bind())
    CLAIMS.create(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "LOCK TABLE order_dispatch_controls IN ACCESS EXCLUSIVE MODE"
    )
    if bind.exec_driver_sql(
        "SELECT 1 FROM order_dispatch_controls LIMIT 1"
    ).first():
        raise RuntimeError("Cannot discard dispatch history")
    CLAIMS.drop(bind)
    CONTROLS.drop(bind)
