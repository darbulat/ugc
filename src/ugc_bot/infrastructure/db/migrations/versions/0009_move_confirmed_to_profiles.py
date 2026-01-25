"""Move instagram_url and confirmed from users to profiles."""

from alembic import op
import sqlalchemy as sa


revision = "0009_move_confirmed_to_profiles"
down_revision = "0008_move_confirmed_to_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Move instagram_url and confirmed from users to profiles."""

    # Add confirmed column back to blogger_profiles
    op.add_column(
        "blogger_profiles",
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Add instagram_url and confirmed to advertiser_profiles
    op.add_column(
        "advertiser_profiles",
        sa.Column("instagram_url", sa.String(), nullable=True),
    )
    op.add_column(
        "advertiser_profiles",
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Create unique constraint on instagram_url in advertiser_profiles
    op.create_unique_constraint(
        "advertiser_profiles_instagram_url_key",
        "advertiser_profiles",
        ["instagram_url"],
    )

    # Migrate data from users to blogger_profiles
    op.execute(
        """
        UPDATE blogger_profiles
        SET confirmed = u.confirmed
        FROM users u
        WHERE blogger_profiles.user_id = u.user_id
        """
    )

    # Migrate instagram_url from users to advertiser_profiles (if user has advertiser profile)
    op.execute(
        """
        UPDATE advertiser_profiles
        SET instagram_url = u.instagram_url,
            confirmed = u.confirmed
        FROM users u
        WHERE advertiser_profiles.user_id = u.user_id
        """
    )

    # Remove columns from users
    op.drop_constraint("users_instagram_url_key", "users", type_="unique")
    op.drop_column("users", "confirmed")
    op.drop_column("users", "instagram_url")


def downgrade() -> None:
    """Restore instagram_url and confirmed to users."""

    # Add columns back to users
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

    # Migrate data from profiles to users
    # For users with blogger profiles, use blogger profile data
    op.execute(
        """
        UPDATE users
        SET instagram_url = bp.instagram_url,
            confirmed = bp.confirmed
        FROM blogger_profiles bp
        WHERE users.user_id = bp.user_id
        """
    )

    # For users with only advertiser profiles, use advertiser profile data
    op.execute(
        """
        UPDATE users
        SET instagram_url = ap.instagram_url,
            confirmed = ap.confirmed
        FROM advertiser_profiles ap
        WHERE users.user_id = ap.user_id
            AND users.instagram_url IS NULL
        """
    )

    # Remove columns from profiles
    op.drop_constraint(
        "advertiser_profiles_instagram_url_key", "advertiser_profiles", type_="unique"
    )
    op.drop_column("advertiser_profiles", "confirmed")
    op.drop_column("advertiser_profiles", "instagram_url")
    op.drop_column("blogger_profiles", "confirmed")
