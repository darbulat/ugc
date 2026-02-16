"""Add accepted column to order_responses."""

import sqlalchemy as sa
from alembic import op

revision = "0039_add_order_responses_accepted"
down_revision = "0038_user_agreement_confirmed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add accepted column to order_responses (true = shown to advertiser)."""
    op.add_column(
        "order_responses",
        sa.Column(
            "accepted", sa.Boolean(), nullable=False, server_default="true"
        ),
    )


def downgrade() -> None:
    """Remove accepted column from order_responses."""
    op.drop_column("order_responses", "accepted")
