"""Authoritative ordering only for an empty, provable journal.

No timestamp/UUID backfill can establish historical causality.
"""

import sqlalchemy as sa
from alembic import op

revision = "journal_append_order"
down_revision = "financial_ledger"
branch_labels = None
depends_on = None


def _guard_empty() -> None:
    conn = op.get_bind()
    # Excludes inserts before checking, and holds through DDL/commit.
    conn.execute(
        sa.text("LOCK TABLE financial_movements IN ACCESS EXCLUSIVE MODE")
    )
    if conn.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM financial_movements)")):
        raise RuntimeError(
            "Journal history exists; append order migration refused"
        )


def upgrade() -> None:
    _guard_empty()
    op.add_column(
        "financial_movements",
        sa.Column(
            "append_order",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_movement_append_order", "financial_movements", ["append_order"]
    )


def downgrade() -> None:
    _guard_empty()
    op.drop_constraint(
        "uq_movement_append_order", "financial_movements", type_="unique"
    )
    op.drop_column("financial_movements", "append_order")
