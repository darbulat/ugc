"""Extend offer_dispatches, migrate from order_responses, drop it."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0040_offer_dispatches_replace_order_responses"
down_revision = "0039_add_order_responses_accepted"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Alter offer_dispatches, migrate from order_responses, drop it."""
    # 1. Rename sent_at -> created_at in offer_dispatches
    op.alter_column(
        "offer_dispatches",
        "sent_at",
        new_column_name="created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
    )

    # 2. Add new columns to offer_dispatches
    op.add_column(
        "offer_dispatches",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "offer_dispatches",
        sa.Column(
            "accepted",
            sa.Boolean(),
            nullable=True,
        ),
    )
    op.add_column(
        "offer_dispatches",
        sa.Column(
            "in_offer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 3. Migrate data from order_responses: update matching offer_dispatches
    op.execute(
        sa.text("""
            UPDATE offer_dispatches d
            SET
                accepted = r.accepted,
                updated_at = r.responded_at,
                in_offer = r.accepted
            FROM order_responses r
            WHERE d.order_id = r.order_id AND d.blogger_id = r.blogger_id
        """)
    )

    # 4. Insert offer_dispatches for order_responses that have no matching row
    op.execute(
        sa.text("""
            INSERT INTO offer_dispatches (
                order_id, blogger_id, created_at, updated_at, accepted, in_offer
            )
            SELECT r.order_id, r.blogger_id, r.responded_at, r.responded_at,
                   r.accepted, r.accepted
            FROM order_responses r
            WHERE NOT EXISTS (
                SELECT 1 FROM offer_dispatches d
                WHERE d.order_id = r.order_id AND d.blogger_id = r.blogger_id
            )
        """)
    )

    # 5. Drop order_responses table (indexes first)
    op.drop_index(
        "ix_order_responses_blogger_id",
        table_name="order_responses",
    )
    op.drop_index(
        "ix_order_responses_order_id",
        table_name="order_responses",
    )
    op.drop_table("order_responses")


def downgrade() -> None:
    """Recreate order_responses from offer_dispatches, revert table."""
    # Recreate order_responses table
    op.create_table(
        "order_responses",
        sa.Column(
            "response_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
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
            "responded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "accepted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.UniqueConstraint("order_id", "blogger_id"),
    )
    op.create_index(
        "ix_order_responses_order_id",
        "order_responses",
        ["order_id"],
    )
    op.create_index(
        "ix_order_responses_blogger_id",
        "order_responses",
        ["blogger_id"],
    )

    # Copy back: rows in offer_dispatches where accepted is not null
    op.execute(
        sa.text("""
            INSERT INTO order_responses (
                order_id, blogger_id, responded_at, accepted
            )
            SELECT order_id, blogger_id,
                   COALESCE(updated_at, created_at), COALESCE(accepted, true)
            FROM offer_dispatches
            WHERE accepted IS NOT NULL
        """)
    )

    # Remove new columns from offer_dispatches
    op.drop_column("offer_dispatches", "in_offer")
    op.drop_column("offer_dispatches", "accepted")
    op.drop_column("offer_dispatches", "updated_at")

    # Rename created_at -> sent_at
    op.alter_column(
        "offer_dispatches",
        "created_at",
        new_column_name="sent_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
    )
