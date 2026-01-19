"""Add payments table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_add_payments"
down_revision = "0003_add_barter_description"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema."""

    payment_status = postgresql.ENUM("pending", "paid", "failed", name="payment_status")
    payment_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "payments",
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "paid",
                "failed",
                name="payment_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade database schema."""

    op.drop_table("payments")
    op.execute('DROP TYPE IF EXISTS "payment_status"')
