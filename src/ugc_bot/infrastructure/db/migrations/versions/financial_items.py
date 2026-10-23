"""Expand v1 policy, items and allocations, without converting historical money.

Revision ID: financial_items
Revises: legacy_financial_guard
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ugc_bot.infrastructure.db.financial_schema import TRIGGER_SQL

revision = "financial_items"
down_revision = "legacy_financial_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("financial_version", sa.String(), nullable=True)
    )
    op.add_column(
        "payments", sa.Column("financial_version", sa.String(), nullable=True)
    )
    op.add_column(
        "payments", sa.Column("captured_minor", sa.BigInteger(), nullable=True)
    )
    op.create_unique_constraint(
        "uq_payment_allocation_scope",
        "payments",
        ["payment_id", "order_id", "currency"],
    )
    op.create_check_constraint(
        "ck_payment_captured_nonnegative",
        "payments",
        "captured_minor IS NULL OR captured_minor >= 0",
    )
    op.create_table(
        "financial_policy_versions",
        sa.Column("version", sa.String(), primary_key=True),
        sa.Column(
            "approved_by",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refund_window_seconds", sa.BigInteger(), nullable=False),
        sa.Column("rules", pg.JSONB(), nullable=False),
        sa.CheckConstraint(
            "refund_window_seconds > 0", name="ck_policy_refund_window_positive"
        ),
    )
    op.create_table(
        "order_items",
        sa.Column("paid_item_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("selection_minor", sa.BigInteger(), nullable=False),
        sa.Column("accompaniment_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "policy_version",
            sa.String(),
            sa.ForeignKey("financial_policy_versions.version"),
            nullable=False,
        ),
        sa.Column(
            "selection_due_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "selection_state",
            sa.String(),
            nullable=False,
            server_default=sa.text("'created'"),
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quote_key", sa.String(), nullable=False),
        sa.Column("quote_payload", pg.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "order_id", "ordinal", name="uq_item_order_ordinal"
        ),
        sa.UniqueConstraint(
            "paid_item_id",
            "order_id",
            "currency",
            name="uq_item_allocation_scope",
        ),
        sa.CheckConstraint("ordinal > 0", name="ck_item_ordinal_positive"),
        sa.CheckConstraint(
            "selection_minor > 0 AND accompaniment_minor >= 0",
            name="ck_item_components_nonnegative",
        ),
        sa.CheckConstraint(
            "currency = 'RUB'", name="ck_item_published_currency"
        ),
    )
    op.create_table(
        "item_assignments",
        sa.Column("assignment_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paid_item_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("order_items.paid_item_id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "creator_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "manager_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "actor_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "paid_item_id", "version", name="uq_assignment_item_version"
        ),
        sa.CheckConstraint(
            "version > 0 AND (valid_to IS NULL OR valid_to >= valid_from)",
            name="ck_assignment_validity",
        ),
    )
    op.create_index(
        "uq_assignment_current_item",
        "item_assignments",
        ["paid_item_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_table(
        "payment_item_allocations",
        sa.Column("allocation_key", sa.String(), primary_key=True),
        sa.Column("payment_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("paid_item_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("component", sa.String(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.ForeignKeyConstraint(
            ["payment_id", "order_id", "currency"],
            ["payments.payment_id", "payments.order_id", "payments.currency"],
            name="fk_allocation_payment_scope",
        ),
        sa.ForeignKeyConstraint(
            ["paid_item_id", "order_id", "currency"],
            [
                "order_items.paid_item_id",
                "order_items.order_id",
                "order_items.currency",
            ],
            name="fk_allocation_item_scope",
        ),
        sa.UniqueConstraint(
            "paid_item_id", "component", name="uq_item_component_allocation"
        ),
        sa.CheckConstraint("amount_minor > 0", name="ck_allocation_positive"),
        sa.CheckConstraint(
            "component IN ('selection', 'accompaniment')",
            name="ck_allocation_component",
        ),
    )
    op.execute(TRIGGER_SQL)


def downgrade() -> None:
    conn = op.get_bind()
    # Serialize every history check and the DDL with financial/bridge writers.
    # Keep the same child-to-parent order as the destructive operations below.
    conn.execute(
        sa.text(
            "LOCK TABLE payment_item_allocations, item_assignments, "
            "order_items, financial_policy_versions, payments, orders "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    if conn.execute(
        sa.text("""
        SELECT 1 FROM order_items
        UNION ALL SELECT 1 FROM financial_policy_versions
        UNION ALL SELECT 1 FROM payments
        WHERE captured_minor IS NOT NULL OR financial_version IS NOT NULL
        UNION ALL SELECT 1 FROM orders WHERE financial_version IS NOT NULL
        LIMIT 1
    """)
    ).first():
        raise RuntimeError(
            "Financial history exists; "
            "disable flags instead of destructive downgrade"
        )
    for table in (
        "payment_item_allocations",
        "item_assignments",
        "order_items",
        "financial_policy_versions",
    ):
        op.drop_table(table)
    op.execute("DROP TRIGGER financial_payment_immutable ON payments")
    for function in (
        "financial_check_allocation",
        "financial_guard_item_price",
        "financial_guard_payment",
        "financial_deny_mutation",
    ):
        op.execute(f"DROP FUNCTION {function}()")
    op.drop_constraint(
        "ck_payment_captured_nonnegative", "payments", type_="check"
    )
    op.drop_constraint(
        "uq_payment_allocation_scope", "payments", type_="unique"
    )
    op.drop_column("payments", "captured_minor")
    op.drop_column("payments", "financial_version")
    op.drop_column("orders", "financial_version")
