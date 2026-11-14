"""Remember whether a creator has dismissed the optional social prompt."""

import sqlalchemy as sa
from alembic import op

revision = "0136_social_prompt_preference"
down_revision = "0135_order_creator_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "social_prompt_dismissed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("blogger_profiles", "social_prompt_dismissed")
