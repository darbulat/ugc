"""Add city, barter, work_format to blogger_profiles."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_blogger_city_barter_fmt"
down_revision = "0008_add_role_chosen_reminder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add city, barter, work_format columns to blogger_profiles."""

    work_format_enum = postgresql.ENUM(
        "ads_in_account",
        "ugc_only",
        name="work_format",
        create_type=True,
    )
    work_format_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "blogger_profiles",
        sa.Column("city", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "barter",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "work_format",
            postgresql.ENUM(
                "ads_in_account",
                "ugc_only",
                name="work_format",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'ugc_only'::work_format"),
        ),
    )


def downgrade() -> None:
    """Remove city, barter, work_format from blogger_profiles."""

    op.drop_column("blogger_profiles", "work_format")
    op.drop_column("blogger_profiles", "barter")
    op.drop_column("blogger_profiles", "city")
    op.execute("DROP TYPE IF EXISTS work_format")
