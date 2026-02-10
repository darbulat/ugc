"""Referral per-user: users.referral_code, user_referral_bindings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030_referral_per_user"
down_revision = "0029_add_referral_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add referral_code, user_referral_bindings; migrate; drop managers."""
    op.add_column(
        "users",
        sa.Column("referral_code", sa.String(32), nullable=True),
    )
    op.create_unique_constraint(
        "uq_users_referral_code", "users", ["referral_code"]
    )

    op.create_table(
        "user_referral_bindings",
        sa.Column(
            "referrer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "referred_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
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

    conn = op.get_bind()
    conn.execute(
        sa.text("""
            INSERT INTO user_referral_bindings
                (referrer_user_id, referred_user_id, created_at)
            SELECT m.user_id, c.creator_user_id, c.created_at
            FROM creator_manager_bindings c
            JOIN managers m ON c.manager_id = m.manager_id
        """)
    )

    op.drop_table("creator_manager_bindings")

    op.add_column(
        "user_referral_pending",
        sa.Column(
            "referrer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    conn.execute(
        sa.text("""
            UPDATE user_referral_pending urp
            SET referrer_user_id = m.user_id
            FROM managers m
            WHERE urp.manager_id = m.manager_id
        """)
    )
    op.drop_constraint(
        "user_referral_pending_pkey",
        "user_referral_pending",
        type_="primary",
    )
    op.drop_column("user_referral_pending", "manager_id")
    op.alter_column(
        "user_referral_pending",
        "referrer_user_id",
        existing_type=postgresql.UUID(),
        nullable=False,
    )
    op.create_primary_key(
        "user_referral_pending_pkey",
        "user_referral_pending",
        ["user_id", "referrer_user_id"],
    )

    op.add_column(
        "payout_requests",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    conn.execute(
        sa.text("""
            UPDATE payout_requests pr
            SET user_id = m.user_id
            FROM managers m
            WHERE pr.manager_id = m.manager_id
        """)
    )
    op.drop_column("payout_requests", "manager_id")
    op.alter_column(
        "payout_requests",
        "user_id",
        existing_type=postgresql.UUID(),
        nullable=False,
    )

    op.drop_table("managers")


def downgrade() -> None:
    """Restore managers and creator_manager_bindings schema. No data restore."""
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

    op.add_column(
        "payout_requests",
        sa.Column(
            "manager_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("managers.manager_id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.drop_column("payout_requests", "user_id")

    op.drop_constraint(
        "user_referral_pending_pkey",
        "user_referral_pending",
        type_="primary",
    )
    op.add_column(
        "user_referral_pending",
        sa.Column(
            "manager_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("managers.manager_id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.drop_column("user_referral_pending", "referrer_user_id")
    op.create_primary_key(
        "user_referral_pending_pkey",
        "user_referral_pending",
        ["user_id", "manager_id"],
    )

    op.drop_table("user_referral_bindings")

    op.drop_constraint("uq_users_referral_code", "users", type_="unique")
    op.drop_column("users", "referral_code")
