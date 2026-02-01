"""Add nps_responses table and wanted_to_change_terms_count to blogger_profiles."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_nps_and_blogger_mark"
down_revision = "0012_site_link_order_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create nps_responses and add wanted_to_change_terms_count."""

    op.create_table(
        "nps_responses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "interaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interactions.interaction_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_nps_responses_interaction_id",
        "nps_responses",
        ["interaction_id"],
        unique=False,
    )

    op.add_column(
        "blogger_profiles",
        sa.Column(
            "wanted_to_change_terms_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """Drop nps_responses and wanted_to_change_terms_count."""

    op.drop_column("blogger_profiles", "wanted_to_change_terms_count")
    op.drop_index("ix_nps_responses_interaction_id", table_name="nps_responses")
    op.drop_table("nps_responses")
