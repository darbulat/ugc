"""Add claimed_at to outbox_events for stale PROCESSING detection."""

import sqlalchemy as sa
from alembic import op

revision = "0061_outbox_claimed_at"
down_revision = "0060_add_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add claimed_at column and index to outbox_events."""
    op.add_column(
        "outbox_events",
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Index for reset_stale_processing_events():
    op.create_index(
        "ix_outbox_events_status_claimed_at",
        "outbox_events",
        ["status", "claimed_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove claimed_at column and index from outbox_events."""
    op.drop_index(
        "ix_outbox_events_status_claimed_at", table_name="outbox_events"
    )
    op.drop_column("outbox_events", "claimed_at")
