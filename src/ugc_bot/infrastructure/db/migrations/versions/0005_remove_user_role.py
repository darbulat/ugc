"""Remove user role column from users."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_remove_user_role"
down_revision = "0004_add_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop role column and enum type."""

    op.drop_column("users", "role")
    op.execute("DROP TYPE IF EXISTS user_role")


def downgrade() -> None:
    """Restore role column and enum type."""

    user_role = postgresql.ENUM("blogger", "advertiser", "both", name="user_role")
    user_role.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "users",
        sa.Column(
            "role",
            postgresql.ENUM(
                "blogger", "advertiser", "both", name="user_role", create_type=False
            ),
            nullable=False,
            server_default="blogger",
        ),
    )
    op.alter_column("users", "role", server_default=None)
