"""Add referral system: managers, creator_manager_bindings, payout_requests."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0029_add_referral_system"
down_revision = "0028_drop_ugc_requirements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create referral system tables."""

    op.create_table(
        "managers",
        sa.Column(
            "manager_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("referral_code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "user_referral_pending",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "manager_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("managers.manager_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "creator_manager_bindings",
        sa.Column(
            "creator_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "manager_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("managers.manager_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    payout_status = postgresql.ENUM(
        "pending", "paid", "cancelled", name="payout_request_status"
    )
    payout_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "payout_requests",
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "manager_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("managers.manager_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "paid",
                "cancelled",
                name="payout_request_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
    )


def downgrade() -> None:
    """Drop referral system tables."""

    op.drop_table("payout_requests")
    op.execute('DROP TYPE IF EXISTS "payout_request_status"')
    op.drop_table("creator_manager_bindings")
    op.drop_table("user_referral_pending")
    op.drop_table("managers")
