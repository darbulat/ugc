"""Drop fsm_drafts table."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0034_drop_fsm_drafts"
down_revision = "0033_user_referral_payout_rate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop fsm_drafts table."""
    op.drop_table("fsm_drafts")


def downgrade() -> None:
    """Recreate fsm_drafts table."""
    op.create_table(
        "fsm_drafts",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("flow_type", sa.String(64), primary_key=True),
        sa.Column("state_key", sa.String(128), nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
