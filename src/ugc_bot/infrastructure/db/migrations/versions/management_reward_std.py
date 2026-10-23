"""Enforce the accepted manager reward, not the customer component price."""

from alembic import op

from ugc_bot.infrastructure.db.management_reward_schema import (
    CONSTRAINT,
    EXPRESSION,
)

revision = "management_reward_std"
down_revision = "management_basis_na"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Validate history while excluding writers; never repair it.
    op.execute("LOCK TABLE financial_obligations IN ACCESS EXCLUSIVE MODE")
    op.create_check_constraint(CONSTRAINT, "financial_obligations", EXPRESSION)


def downgrade() -> None:
    # Drop only this rule, not facts; never roll back app code automatically.
    op.execute("LOCK TABLE financial_obligations IN ACCESS EXCLUSIVE MODE")
    op.drop_constraint(CONSTRAINT, "financial_obligations", type_="check")
