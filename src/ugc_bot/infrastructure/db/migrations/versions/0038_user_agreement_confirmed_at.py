"""Add agreement_confirmed_at to users."""

import sqlalchemy as sa
from alembic import op

revision = "0038_user_agreement_confirmed_at"
down_revision = "0037_blogger_gender"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add agreement_confirmed_at column to users."""
    op.add_column(
        "users",
        sa.Column(
            "agreement_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove agreement_confirmed_at from users."""
    op.drop_column("users", "agreement_confirmed_at")
