"""Add created_at and updated_at to main tables where missing."""

import sqlalchemy as sa
from alembic import op

revision = "0043_add_created_at_updated_at_main_tables"
down_revision = "0042_blogger_profiles_instagram_stats_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add created_at/updated_at to main tables."""
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "advertiser_profiles",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "advertiser_profiles",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "contact_pricing",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "complaints",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "payments",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "payout_requests",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    """Remove created_at/updated_at from main tables."""
    op.drop_column("payout_requests", "updated_at")
    op.drop_column("payments", "updated_at")
    op.drop_column("complaints", "updated_at")
    op.drop_column("contact_pricing", "created_at")
    op.drop_column("orders", "updated_at")
    op.drop_column("advertiser_profiles", "updated_at")
    op.drop_column("advertiser_profiles", "created_at")
    op.drop_column("blogger_profiles", "created_at")
    op.drop_column("users", "updated_at")
