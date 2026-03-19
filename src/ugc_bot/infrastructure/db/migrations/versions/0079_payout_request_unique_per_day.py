"""Add unique partial index per payout request user+currency+day."""

from alembic import op

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_payout_request_user_currency_day
        ON payout_requests (
            user_id,
            currency,
            DATE(requested_at AT TIME ZONE 'UTC')
        )
        WHERE status NOT IN ('cancelled', 'deleted')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_payout_request_user_currency_day")
