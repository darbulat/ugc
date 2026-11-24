"""Coalesce Instagram rechecks across offers and delivery workers."""

import sqlalchemy as sa
from alembic import op

revision = "0150_instagram_offer_checks"
down_revision = "0149_offer_response_started"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instagram_offer_checks",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("meta_id", sa.String(100), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("instagram_offer_checks")
