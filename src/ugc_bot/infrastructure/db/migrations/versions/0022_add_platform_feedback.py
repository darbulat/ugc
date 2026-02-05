"""Add platform_feedback table for UMC platform rating (1-5 stars + comment)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0022_add_platform_feedback"
down_revision = "0021_add_complaint_file_ids_user_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create platform_feedback table."""

    op.create_table(
        "platform_feedback",
        sa.Column(
            "feedback_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_type", sa.String(8), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_platform_feedback_order_id",
        "platform_feedback",
        ["order_id"],
        unique=False,
    )
    op.create_index(
        "ix_platform_feedback_user_id",
        "platform_feedback",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop platform_feedback table."""

    op.drop_index("ix_platform_feedback_user_id", table_name="platform_feedback")
    op.drop_index("ix_platform_feedback_order_id", table_name="platform_feedback")
    op.drop_table("platform_feedback")
