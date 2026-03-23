"""Replace referral_income_entries unique constraint.

The old constraint (order_id, referrer_user_id, income_type) prevented
recording income for multiple referred users (creators) in the same order.
The new constraint adds referred_user_id so each blogger gets their own entry.

Revision ID: 0083
Revises: 0082
"""

from alembic import op

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_referral_income_order_referrer_type",
        "referral_income_entries",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_referral_income_order_referrer_referred_type",
        "referral_income_entries",
        ["order_id", "referrer_user_id", "referred_user_id", "income_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_referral_income_order_referrer_referred_type",
        "referral_income_entries",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_referral_income_order_referrer_type",
        "referral_income_entries",
        ["order_id", "referrer_user_id", "income_type"],
    )
