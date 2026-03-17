"""Add country_code and currency to contact_pricing, make composite PK."""

import sqlalchemy as sa
from alembic import op

revision = "0071_contact_pricing_country"
down_revision = "0070_country_tax_rate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contact_pricing",
        sa.Column(
            "country_code",
            sa.String(2),
            nullable=False,
            server_default=sa.text("'ru'"),
        ),
    )
    op.add_column(
        "contact_pricing",
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'RUB'"),
        ),
    )
    op.drop_constraint(
        "contact_pricing_pkey", "contact_pricing", type_="primary"
    )
    op.create_primary_key(
        "contact_pricing_pkey",
        "contact_pricing",
        ["country_code", "bloggers_count"],
    )
    op.create_foreign_key(
        "fk_contact_pricing_country",
        "contact_pricing",
        "countries",
        ["country_code"],
        ["code"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_contact_pricing_country", "contact_pricing", type_="foreignkey"
    )
    op.drop_constraint(
        "contact_pricing_pkey", "contact_pricing", type_="primary"
    )
    op.create_primary_key(
        "contact_pricing_pkey", "contact_pricing", ["bloggers_count"]
    )
    op.drop_column("contact_pricing", "currency")
    op.drop_column("contact_pricing", "country_code")
