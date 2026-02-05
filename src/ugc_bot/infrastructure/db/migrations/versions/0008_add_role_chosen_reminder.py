"""Add role_chosen_at and last_role_reminder_at to users."""

import sqlalchemy as sa
from alembic import op

revision = "0008_add_role_chosen_reminder"
down_revision = "0007_interaction_postpone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add role choice and reminder fields to users."""

    op.add_column(
        "users",
        sa.Column(
            "role_chosen_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "last_role_reminder_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove role choice and reminder fields from users."""

    op.drop_column("users", "last_role_reminder_at")
    op.drop_column("users", "role_chosen_at")
