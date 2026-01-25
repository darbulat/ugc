"""Merge blogger/advertiser profiles into users and add roles."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_merge_profiles_into_users"
down_revision = "0009_move_confirmed_to_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Move profile data into users and drop profile tables."""

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
    op.add_column("users", sa.Column("instagram_url", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("users", sa.Column("topics", postgresql.JSONB(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "audience_gender",
            postgresql.ENUM("m", "f", "all", name="audience_gender", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("users", sa.Column("audience_age_min", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("audience_age_max", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("audience_geo", sa.String(), nullable=True))
    op.add_column("users", sa.Column("price", sa.Numeric(10, 2), nullable=True))
    op.add_column("users", sa.Column("contact", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("profile_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("users_instagram_url_key", "users", ["instagram_url"])

    op.execute(
        """
        UPDATE users u
        SET instagram_url = bp.instagram_url,
            confirmed = bp.confirmed,
            topics = bp.topics,
            audience_gender = bp.audience_gender,
            audience_age_min = bp.audience_age_min,
            audience_age_max = bp.audience_age_max,
            audience_geo = bp.audience_geo,
            price = bp.price,
            profile_updated_at = bp.updated_at
        FROM blogger_profiles bp
        WHERE u.user_id = bp.user_id
        """
    )
    op.execute(
        """
        UPDATE users u
        SET contact = ap.contact,
            instagram_url = COALESCE(u.instagram_url, ap.instagram_url),
            confirmed = CASE WHEN u.confirmed THEN u.confirmed ELSE ap.confirmed END
        FROM advertiser_profiles ap
        WHERE u.user_id = ap.user_id
        """
    )
    op.execute(
        """
        UPDATE users
        SET role = 'both'
        WHERE EXISTS (SELECT 1 FROM blogger_profiles bp WHERE bp.user_id = users.user_id)
          AND EXISTS (SELECT 1 FROM advertiser_profiles ap WHERE ap.user_id = users.user_id)
        """
    )
    op.execute(
        """
        UPDATE users
        SET role = 'advertiser'
        WHERE role = 'blogger'
          AND EXISTS (SELECT 1 FROM advertiser_profiles ap WHERE ap.user_id = users.user_id)
          AND NOT EXISTS (SELECT 1 FROM blogger_profiles bp WHERE bp.user_id = users.user_id)
        """
    )

    op.drop_table("advertiser_profiles")
    op.drop_table("blogger_profiles")
    op.alter_column("users", "role", server_default=None)


def downgrade() -> None:
    """Restore profile tables and remove merged columns."""

    op.create_table(
        "blogger_profiles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("instagram_url", sa.String(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "topics",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "audience_gender",
            postgresql.ENUM("m", "f", "all", name="audience_gender", create_type=False),
            nullable=False,
        ),
        sa.Column("audience_age_min", sa.Integer(), nullable=False),
        sa.Column("audience_age_max", sa.Integer(), nullable=False),
        sa.Column("audience_geo", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("instagram_url", name="blogger_profiles_instagram_url_key"),
    )
    op.create_table(
        "advertiser_profiles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("instagram_url", sa.String(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("contact", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "instagram_url", name="advertiser_profiles_instagram_url_key"
        ),
    )

    op.execute(
        """
        INSERT INTO blogger_profiles (
            user_id,
            instagram_url,
            confirmed,
            topics,
            audience_gender,
            audience_age_min,
            audience_age_max,
            audience_geo,
            price,
            updated_at
        )
        SELECT
            user_id,
            instagram_url,
            confirmed,
            COALESCE(topics, '{}'::jsonb),
            COALESCE(audience_gender, 'all'),
            COALESCE(audience_age_min, 18),
            COALESCE(audience_age_max, 65),
            COALESCE(audience_geo, ''),
            COALESCE(price, 0),
            COALESCE(profile_updated_at, now())
        FROM users
        WHERE role IN ('blogger', 'both')
          AND instagram_url IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO advertiser_profiles (
            user_id,
            instagram_url,
            confirmed,
            contact
        )
        SELECT
            user_id,
            instagram_url,
            confirmed,
            COALESCE(contact, '')
        FROM users
        WHERE role IN ('advertiser', 'both')
        """
    )

    op.drop_constraint("users_instagram_url_key", "users", type_="unique")
    op.drop_column("users", "profile_updated_at")
    op.drop_column("users", "contact")
    op.drop_column("users", "price")
    op.drop_column("users", "audience_geo")
    op.drop_column("users", "audience_age_max")
    op.drop_column("users", "audience_age_min")
    op.drop_column("users", "audience_gender")
    op.drop_column("users", "topics")
    op.drop_column("users", "confirmed")
    op.drop_column("users", "instagram_url")
    op.drop_column("users", "role")
    op.execute("DROP TYPE IF EXISTS user_role")
