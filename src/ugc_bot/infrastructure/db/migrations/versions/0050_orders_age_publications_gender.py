"""Add order admin filters: age, publications, gender."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0050_orders_age_publications_gender"
down_revision = "0049_blogger_profile_birth_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add optional admin-only filter columns to orders."""
    op.add_column(
        "orders",
        sa.Column("min_age", sa.Integer(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("max_age", sa.Integer(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("min_publications", sa.Integer(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("max_publications", sa.Integer(), nullable=True),
    )
    blogger_gender_enum = postgresql.ENUM(
        "m",
        "f",
        name="blogger_gender",
        create_type=False,
    )
    op.add_column(
        "orders",
        sa.Column(
            "required_blogger_gender",
            blogger_gender_enum,
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove filter columns from orders."""
    op.drop_column("orders", "required_blogger_gender")
    op.drop_column("orders", "max_publications")
    op.drop_column("orders", "min_publications")
    op.drop_column("orders", "max_age")
    op.drop_column("orders", "min_age")
