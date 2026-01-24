"""Move instagram_url and confirmed from blogger_profiles to users."""

from alembic import op
import sqlalchemy as sa


revision = "0008_move_confirmed_to_user"
down_revision = "0007_interaction_postpone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Move instagram_url and confirmed to users table."""

    # Add new columns to users table
    op.add_column(
        "users",
        sa.Column("instagram_url", sa.String(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Create unique constraint on instagram_url in users
    op.create_unique_constraint("users_instagram_url_key", "users", ["instagram_url"])

    # Migrate data from blogger_profiles to users
    op.execute(
        """
        UPDATE users
        SET instagram_url = bp.instagram_url,
            confirmed = bp.confirmed
        FROM blogger_profiles bp
        WHERE users.user_id = bp.user_id
        """
    )

    # Remove confirmed column from blogger_profiles
    op.drop_column("blogger_profiles", "confirmed")


def downgrade() -> None:
    """Restore confirmed to blogger_profiles."""

    # Add confirmed column back to blogger_profiles
    op.add_column(
        "blogger_profiles",
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Migrate data back from users to blogger_profiles
    op.execute(
        """
        UPDATE blogger_profiles
        SET confirmed = u.confirmed
        FROM users u
        WHERE blogger_profiles.user_id = u.user_id
        """
    )

    # Remove columns from users
    op.drop_constraint("users_instagram_url_key", "users", type_="unique")
    op.drop_column("users", "confirmed")
    op.drop_column("users", "instagram_url")
