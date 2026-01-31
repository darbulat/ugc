"""Add fsm_drafts table for saving partial form data on Support."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0011_fsm_drafts"
down_revision = "0010_advertiser_name_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create fsm_drafts table."""

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


def downgrade() -> None:
    """Drop fsm_drafts table."""

    op.drop_table("fsm_drafts")
