"""Persist a creator's optional social setup dismissal."""

import sqlalchemy as sa
from alembic import op

revision = "0137_social_prompt_preference"
down_revision = "0136_manager_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_social_prompt_dismissals",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("blogger_profiles.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("creator_social_prompt_dismissals")
