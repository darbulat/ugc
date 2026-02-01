"""Add site_link to advertiser_profiles and order_type to orders."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_site_link_order_type"
down_revision = "0011_fsm_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add site_link to advertiser_profiles and order_type to orders."""

    op.add_column(
        "advertiser_profiles",
        sa.Column("site_link", sa.String(), nullable=True),
    )

    order_type_enum = postgresql.ENUM(
        "ugc_only",
        "ugc_plus_placement",
        name="order_type",
        create_type=True,
    )
    order_type_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "orders",
        sa.Column(
            "order_type",
            postgresql.ENUM(
                "ugc_only",
                "ugc_plus_placement",
                name="order_type",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'ugc_only'::order_type"),
        ),
    )


def downgrade() -> None:
    """Remove site_link and order_type."""

    op.drop_column("orders", "order_type")
    op.execute("DROP TYPE IF EXISTS order_type")

    op.drop_column("advertiser_profiles", "site_link")
