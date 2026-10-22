"""Persist legacy dispute safety-stops without changing historical earnings.

Revision ID: legacy_financial_guard
Revises: 0092
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "legacy_financial_guard"
down_revision = "0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legacy_financial_cases",
        sa.Column(
            "interaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interactions.interaction_id"),
            primary_key=True,
        ),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("cause", sa.String(80), nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "released",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "legacy_financial_case_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "interaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legacy_financial_cases.interaction_id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "command_id",
            postgresql.UUID(as_uuid=True),
            unique=True,
            nullable=True,
        ),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "legacy_financial_guards",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "interaction_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["interactions.interaction_id"]
        ),
        sa.PrimaryKeyConstraint("user_id", "currency", "interaction_id"),
    )


def downgrade() -> None:
    # Never discard review history, even when all cases have been released.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE legacy_financial_cases, "
            "legacy_financial_case_events, legacy_financial_guards IN "
            "ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.execute(
        sa.text("SELECT 1 FROM legacy_financial_cases LIMIT 1")
    ).first():
        raise RuntimeError("Cannot remove legacy financial case history")
    # Removing a safety-stop while disputed money exists is not a safe rollback.
    connection = op.get_bind()
    # Serialize the empty check and DROP with every concurrent guard writer.
    connection.execute(
        sa.text("LOCK TABLE legacy_financial_guards IN ACCESS EXCLUSIVE MODE")
    )
    if connection.execute(
        sa.text("SELECT 1 FROM legacy_financial_guards LIMIT 1")
    ).first():
        raise RuntimeError("Cannot remove active legacy dispute guards")
    op.drop_table("legacy_financial_guards")
    op.drop_table("legacy_financial_case_events")
    op.drop_table("legacy_financial_cases")
