"""Add contact pricing table."""

import sqlalchemy as sa
from alembic import op

revision = "0006_add_contact_pricing"
down_revision = "0005_remove_user_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create contact pricing table and seed defaults."""

    op.create_table(
        "contact_pricing",
        sa.Column("bloggers_count", sa.Integer(), primary_key=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute(
        "INSERT INTO contact_pricing (bloggers_count, price) VALUES "
        "(3, 0), (10, 0), (20, 0), (30, 0), (50, 0)"
    )


def downgrade() -> None:
    """Drop contact pricing table."""

    op.drop_table("contact_pricing")
