"""Add referral_income_entries table and currency to payout_requests."""

import sqlalchemy as sa
from alembic import op

revision = "0072_referral_income_entries"
down_revision = "0071_contact_pricing_country"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create referral_income_entries table, add currency to payout_requests."""
    op.create_table(
        "referral_income_entries",
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("referrer_user_id", sa.UUID(), nullable=False),
        sa.Column("referred_user_id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("income_type", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("platform_revenue", sa.Numeric(10, 2), nullable=False),
        sa.Column("commission_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("commission_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("entry_id"),
        sa.ForeignKeyConstraint(
            ["referrer_user_id"],
            ["users.user_id"],
            name="fk_referral_income_referrer",
        ),
        sa.ForeignKeyConstraint(
            ["referred_user_id"],
            ["users.user_id"],
            name="fk_referral_income_referred",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.order_id"],
            name="fk_referral_income_order",
        ),
        sa.UniqueConstraint(
            "order_id",
            "referrer_user_id",
            "income_type",
            name="uq_referral_income_order_referrer_type",
        ),
    )
    op.create_index(
        "ix_referral_income_entries_referrer",
        "referral_income_entries",
        ["referrer_user_id"],
    )

    op.add_column(
        "payout_requests",
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'RUB'"),
        ),
    )


def downgrade() -> None:
    """Revert changes."""
    op.drop_column("payout_requests", "currency")
    op.drop_table("referral_income_entries")
