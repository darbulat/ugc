"""Allow policy-scoped selection maturity after each accepted delivery."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.selection_maturity_schema import (
    PER_ITEM_SELECTION_SOURCE_GUARD,
    SELECTION_SOURCE_GUARD,
)

revision = "0128_selection_per_item"
down_revision = "0127_public_policy_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "financial_selection_schedules", "closure_id", nullable=True
    )
    # Existing rows may have been accepted under another session time zone;
    # retain them as historical facts while enforcing the new check on writes.
    op.drop_constraint(
        "ck_selection_maturity_hold",
        "financial_selection_schedules",
        type_="check",
    )
    op.execute(
        "ALTER TABLE financial_selection_schedules ADD CONSTRAINT "
        "ck_selection_maturity_hold CHECK ((closure_id IS NOT NULL AND "
        "release_at=hold_started_at+INTERVAL '14 days') OR "
        "(closure_id IS NULL AND "
        "release_at=hold_started_at+1209600*INTERVAL '1 second')) NOT VALID"
    )
    op.execute(PER_ITEM_SELECTION_SOURCE_GUARD)


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "LOCK TABLE financial_selection_schedules, financial_policy_versions "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if bind.execute(
        sa.text(
            "SELECT 1 FROM financial_selection_schedules "
            "WHERE closure_id IS NULL "
            "UNION ALL SELECT 1 FROM financial_policy_versions "
            "WHERE rules->>'maturity_mode'='per_item_v1' LIMIT 1"
        )
    ).first():
        raise RuntimeError(
            "Cannot downgrade per-item selection maturity history"
        )
    op.execute(SELECTION_SOURCE_GUARD)
    op.drop_constraint(
        "ck_selection_maturity_hold",
        "financial_selection_schedules",
        type_="check",
    )
    op.execute(
        "ALTER TABLE financial_selection_schedules ADD CONSTRAINT "
        "ck_selection_maturity_hold "
        "CHECK (release_at=hold_started_at+INTERVAL '14 days') NOT VALID"
    )
    op.alter_column(
        "financial_selection_schedules", "closure_id", nullable=False
    )
