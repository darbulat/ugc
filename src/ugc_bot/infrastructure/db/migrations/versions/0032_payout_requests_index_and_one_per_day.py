"""Add referral indexes: payout_requests (user_id, one-per-day), bindings."""

from alembic import op

revision = "0032_payout_requests_index_and_one_per_day"
down_revision = "0031_payout_request_amount"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add indexes for payout_requests and user_referral_bindings."""
    op.create_index(
        "ix_payout_requests_user_id",
        "payout_requests",
        ["user_id"],
        unique=False,
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_payout_requests_user_id_request_date "
        "ON payout_requests (user_id, (CAST(requested_at AT TIME ZONE 'UTC' AS date)))"
    )
    op.create_index(
        "ix_user_referral_bindings_referred_user_id",
        "user_referral_bindings",
        ["referred_user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove indexes."""
    op.drop_index(
        "ix_user_referral_bindings_referred_user_id",
        table_name="user_referral_bindings",
    )
    op.execute("DROP INDEX IF EXISTS uq_payout_requests_user_id_request_date")
    op.drop_index(
        "ix_payout_requests_user_id",
        table_name="payout_requests",
    )
