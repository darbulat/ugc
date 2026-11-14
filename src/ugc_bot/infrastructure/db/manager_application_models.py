"""Manager applications and evidence of Telegram and Instagram ownership."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base


def application_table(metadata):
    return sa.Table(
        "manager_applications",
        metadata,
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id"),
            primary_key=True,
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("decision_note", sa.String(300)),
        sa.Column(
            "registered_by_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("instagram", sa.String(30)),
        sa.Column("instagram_user_id", sa.String(100), unique=True),
        sa.Column("instagram_verified_at", sa.DateTime(timezone=True)),
        sa.Column("challenge", sa.String(20), unique=True),
        sa.Column("challenge_until", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('draft', 'submitted', 'clarify', "
            "'approved', 'declined')",
            name="ck_manager_application_state",
        ),
    )


APPLICATIONS = application_table(Base.metadata)
