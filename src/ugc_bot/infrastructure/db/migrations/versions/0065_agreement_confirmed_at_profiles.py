"""Move agreement_confirmed_at from users to blogger/advertiser profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0065_agreement_confirmed_at_profiles"
down_revision = "0064_bot_texts_country_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add agreement_confirmed_at to profiles; drop from users."""
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "agreement_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "advertiser_profiles",
        sa.Column(
            "agreement_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Migrate existing data: copy agreement_confirmed_at from users to profiles
    op.execute(
        """
        UPDATE blogger_profiles bp
        SET agreement_confirmed_at = u.agreement_confirmed_at
        FROM users u
        WHERE bp.user_id = u.user_id
          AND u.agreement_confirmed_at IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE advertiser_profiles ap
        SET agreement_confirmed_at = u.agreement_confirmed_at
        FROM users u
        WHERE ap.user_id = u.user_id
          AND u.agreement_confirmed_at IS NOT NULL
        """
    )

    op.drop_column("users", "agreement_confirmed_at")


def downgrade() -> None:
    """Restore agreement_confirmed_at on users; drop from profile tables."""
    op.add_column(
        "users",
        sa.Column(
            "agreement_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Migrate data back: prefer blogger profile, fallback to advertiser
    op.execute(
        """
        UPDATE users u
        SET agreement_confirmed_at = COALESCE(
            (SELECT bp.agreement_confirmed_at
             FROM blogger_profiles bp WHERE bp.user_id = u.user_id),
            (SELECT ap.agreement_confirmed_at
             FROM advertiser_profiles ap WHERE ap.user_id = u.user_id)
        )
        """
    )

    op.drop_column("advertiser_profiles", "agreement_confirmed_at")
    op.drop_column("blogger_profiles", "agreement_confirmed_at")
