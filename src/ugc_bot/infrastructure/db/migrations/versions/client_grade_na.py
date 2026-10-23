"""Truthful not-applicable CLIENT grade without rewriting immutable history."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.snapshot_grade_schema import (
    CONSTRAINT,
    EXPRESSION,
)

revision = "client_grade_na"
down_revision = "journal_append_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("rate_snapshots", "verified_count", nullable=True)
    op.create_check_constraint(CONSTRAINT, "rate_snapshots", EXPRESSION)


def downgrade() -> None:
    # Lock before inspecting history; never backfill a fabricated zero.
    op.execute("LOCK TABLE rate_snapshots IN ACCESS EXCLUSIVE MODE")
    conn = op.get_bind()
    if conn.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM rate_snapshots "
            "WHERE verified_count IS NULL)"
        )
    ):
        raise RuntimeError("client_grade_na_history_prevents_downgrade")
    op.drop_constraint(CONSTRAINT, "rate_snapshots", type_="check")
    op.alter_column("rate_snapshots", "verified_count", nullable=False)
