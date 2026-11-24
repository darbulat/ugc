"""Record the first click on a creator's offer response button."""

import sqlalchemy as sa
from alembic import op

revision = "0149_offer_response_started"
down_revision = "0148_offer_reserve_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "offer_channel_attribution",
        sa.Column("response_started_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("offer_channel_attribution", "response_started_at")
