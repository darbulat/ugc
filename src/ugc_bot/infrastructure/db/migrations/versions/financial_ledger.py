"""Expand ledger storage; never import historical decimal balances.

Revision ID: financial_ledger
Revises: financial_items
"""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.ledger_schema import NAMES, ledger_tables

revision = "financial_ledger"
down_revision = "financial_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_assignment_id_item",
        "item_assignments",
        ["assignment_id", "paid_item_id"],
    )
    metadata = sa.MetaData()
    metadata.reflect(
        op.get_bind(),
        only=[
            "users",
            "order_items",
            "item_assignments",
            "payments",
            "payout_requests",
            "financial_policy_versions",
        ],
    )
    for table in ledger_tables(metadata).values():
        table.create(op.get_bind())


def downgrade() -> None:
    conn = op.get_bind()
    # The emptiness observation and destructive DDL must serialize with inserts.
    conn.execute(
        sa.text("LOCK TABLE " + ", ".join(NAMES) + " IN ACCESS EXCLUSIVE MODE")
    )
    # Fail before any DDL, including when only snapshots/audit/projection exist.
    for name in NAMES:
        if conn.scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {name})")):
            raise RuntimeError("Financial history exists; downgrade refused")
    for name in reversed(NAMES):
        op.drop_table(name)
    op.execute("DROP FUNCTION ledger_deny_mutation()")
    op.execute("DROP FUNCTION ledger_check_obligation_scope()")
    op.drop_constraint(
        "uq_assignment_id_item", "item_assignments", type_="unique"
    )
