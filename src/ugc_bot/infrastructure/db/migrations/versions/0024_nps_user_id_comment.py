"""Add user_id and comment to nps_responses, remove interaction_id."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024_nps_user_id_comment"
down_revision = "0023_drop_platform_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add user_id and comment, migrate data, remove interaction_id."""

    op.add_column(
        "nps_responses",
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.add_column(
        "nps_responses",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE nps_responses n
        SET user_id = i.advertiser_id
        FROM interactions i
        WHERE n.interaction_id = i.interaction_id
        """
    )
    op.alter_column(
        "nps_responses",
        "user_id",
        nullable=False,
    )
    op.drop_index("ix_nps_responses_interaction_id", table_name="nps_responses")
    op.drop_constraint(
        "nps_responses_interaction_id_fkey",
        "nps_responses",
        type_="foreignkey",
    )
    op.drop_column("nps_responses", "interaction_id")
    op.create_index(
        "ix_nps_responses_user_id",
        "nps_responses",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Revert to interaction_id, remove user_id and comment."""

    op.add_column(
        "nps_responses",
        sa.Column(
            "interaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interactions.interaction_id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE nps_responses n
        SET interaction_id = (
            SELECT i.interaction_id
            FROM interactions i
            WHERE i.advertiser_id = n.user_id
            LIMIT 1
        )
        """
    )
    op.alter_column(
        "nps_responses",
        "interaction_id",
        nullable=False,
    )
    op.drop_index("ix_nps_responses_user_id", table_name="nps_responses")
    op.drop_column("nps_responses", "user_id")
    op.drop_column("nps_responses", "comment")
    op.create_index(
        "ix_nps_responses_interaction_id",
        "nps_responses",
        ["interaction_id"],
        unique=False,
    )
