"""Represent a fixed management fee without invented referral attributes."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.management_basis_schema import (
    GRADE_EXPRESSION,
    GRADE_NAME,
    MANAGEMENT_EXPRESSION,
    MANAGEMENT_NAME,
    REFERRAL_EXPRESSION,
    REFERRAL_NAME,
)
from ugc_bot.infrastructure.db.snapshot_grade_schema import (
    EXPRESSION as OLD_GRADE_EXPRESSION,
)

revision = "management_basis_na"
down_revision = "client_grade_na"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE rate_snapshots IN ACCESS EXCLUSIVE MODE")
    for column in ("registered_at", "rate_bps"):
        op.alter_column("rate_snapshots", column, nullable=True)
    op.drop_constraint(GRADE_NAME, "rate_snapshots", type_="check")
    for name, expression in (
        (GRADE_NAME, GRADE_EXPRESSION),
        (REFERRAL_NAME, REFERRAL_EXPRESSION),
        (MANAGEMENT_NAME, MANAGEMENT_EXPRESSION),
    ):
        op.create_check_constraint(name, "rate_snapshots", expression)


def downgrade() -> None:
    op.execute("LOCK TABLE rate_snapshots IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM rate_snapshots "
            "WHERE registered_at IS NULL OR rate_bps IS NULL)"
        )
    ):
        raise RuntimeError("management_basis_na_history_prevents_downgrade")
    for name in (MANAGEMENT_NAME, REFERRAL_NAME, GRADE_NAME):
        op.drop_constraint(name, "rate_snapshots", type_="check")
    op.create_check_constraint(
        GRADE_NAME, "rate_snapshots", OLD_GRADE_EXPRESSION
    )
    for column in ("registered_at", "rate_bps"):
        op.alter_column("rate_snapshots", column, nullable=False)
