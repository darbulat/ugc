"""add_outbox_events_table"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "7b07c4b86f09"
down_revision = "0006_add_contact_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema."""

    op.create_table(
        "outbox_events",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("aggregate_id", sa.String(), nullable=False),
        sa.Column("aggregate_type", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "retry_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
        sa.Index("ix_outbox_events_event_type", "event_type"),
        sa.Index("ix_outbox_events_aggregate_id", "aggregate_id"),
        sa.Index("ix_outbox_events_status", "status"),
    )


def downgrade() -> None:
    """Downgrade database schema."""

    op.drop_table("outbox_events")
