"""Distinguish preparation leases from potentially delivered sends."""

from alembic import op

revision = "0125_order_notice_leases"
down_revision = "0124_order_notices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_order_notice_delivery_state",
        "order_notice_deliveries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_order_notice_delivery_state",
        "order_notice_deliveries",
        "state IN ('pending','leased','sending','sent','failed','unknown')",
    )


def downgrade() -> None:
    # A lease proves no provider call has started, so it can safely be retried.
    op.execute(
        "UPDATE order_notice_deliveries SET state = 'pending', "
        "lease_until = NULL WHERE state = 'leased'"
    )
    op.drop_constraint(
        "ck_order_notice_delivery_state",
        "order_notice_deliveries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_order_notice_delivery_state",
        "order_notice_deliveries",
        "state IN ('pending','sending','sent','failed','unknown')",
    )
