"""Add blogger_gender to blogger_profiles."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037_blogger_gender"
down_revision = "0036_add_dashboard_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add blogger_gender column to blogger_profiles."""
    blogger_gender_enum = postgresql.ENUM(
        "m",
        "f",
        name="blogger_gender",
        create_type=True,
    )
    blogger_gender_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "blogger_profiles",
        sa.Column(
            "blogger_gender",
            postgresql.ENUM("m", "f", name="blogger_gender", create_type=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove blogger_gender from blogger_profiles."""
    op.drop_column("blogger_profiles", "blogger_gender")
    op.execute("DROP TYPE IF EXISTS blogger_gender")
