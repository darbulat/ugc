"""Current append ordering; keep the released foundation schema frozen."""

import sqlalchemy as sa


def add_journal_order(table: sa.Table) -> None:
    table.append_column(
        sa.Column(
            "append_order",
            sa.BigInteger,
            sa.Identity(always=True),
            nullable=False,
        )
    )
    table.append_constraint(
        sa.UniqueConstraint("append_order", name="uq_movement_append_order")
    )
