"""Add postpone_count, next_check_at, updated_at to interactions and PENDING status."""

from alembic import op
import sqlalchemy as sa

revision = "0007_interaction_postpone"
down_revision = "7b07c4b86f09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add postpone fields and PENDING status to interactions."""

    # Add PENDING to interaction_status enum
    op.execute("ALTER TYPE interaction_status ADD VALUE IF NOT EXISTS 'pending'")

    # Add new columns to interactions table
    op.add_column(
        "interactions",
        sa.Column("postpone_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "interactions",
        sa.Column(
            "next_check_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "interactions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    """Remove postpone fields from interactions."""

    op.drop_column("interactions", "updated_at")
    op.drop_column("interactions", "next_check_at")
    op.drop_column("interactions", "postpone_count")

    # Note: Cannot remove enum value 'pending' in PostgreSQL easily
    # This would require recreating the enum type
