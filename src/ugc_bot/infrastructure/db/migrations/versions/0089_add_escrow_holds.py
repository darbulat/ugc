"""Add escrow_holds table for per-blogger payment escrow.

Revision ID: 0089
Revises: 0088
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0089"
down_revision = "0088"


def upgrade() -> None:
    escrow_status = postgresql.ENUM(
        "held",
        "released",
        "refunded",
        "disputed",
        "cancelled",
        name="escrow_status",
        create_type=False,
    )
    escrow_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "escrow_holds",
        sa.Column(
            "escrow_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payments.payment_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "blogger_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "interaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interactions.interaction_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            escrow_status,
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "released_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "refunded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.create_index("ix_escrow_holds_status", "escrow_holds", ["status"])
    op.create_index(
        "ix_escrow_holds_payment_id", "escrow_holds", ["payment_id"]
    )
    op.create_index(
        "ix_escrow_holds_interaction_id", "escrow_holds", ["interaction_id"]
    )
    op.create_index(
        "ix_escrow_holds_order_id_status",
        "escrow_holds",
        ["order_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("escrow_holds")
    op.execute("DROP TYPE IF EXISTS escrow_status")
