"""Persist reminders in the manager's creator directory."""

import sqlalchemy as sa
from alembic import op

revision = "0143_manager_creator_followups"
down_revision = "0142_creator_offer_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_creator_followups",
        sa.Column(
            "manager_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
        ),
        sa.Column(
            "creator_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
        ),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("manager_id", "creator_id"),
    )


def downgrade() -> None:
    op.drop_table("manager_creator_followups")
