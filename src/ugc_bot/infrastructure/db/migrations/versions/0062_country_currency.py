"""Add countries table; country to users; currency to profiles/orders."""

import sqlalchemy as sa
from alembic import op

revision = "0062_country_currency"
down_revision = "0061_outbox_claimed_at"
branch_labels = None
depends_on = None

# Countries seed data
_COUNTRIES = [
    ("ru", "Россия", "RUB", "₽"),
    ("by", "Беларусь", "BYN", "Br"),
    ("kz", "Қазақстан", "KZT", "₸"),
    ("kg", "Кыргызстан", "KGS", "с"),
    ("am", "Հայաստան", "AMD", "֏"),
    ("uz", "Oʻzbekiston", "UZS", "сўм"),
    ("ge", "საქართველო", "GEL", "₾"),
    ("ab", "Аҧсны", "RUB", "₽"),
]

# Normalization map: lowercase existing country values → 2-letter code
_NORMALIZE = {
    "russia": "ru",
    "россия": "ru",
    "georgia": "ge",
    "kyrgyzstan": "kg",
    "казахстан": "kz",
    "kazakhstan": "kz",
    "belarus": "by",
    "беларусь": "by",
    "abkhazia": "ab",
    "армения": "am",
    "armenia": "am",
    "uzbekistan": "uz",
}

# Currency code per country code
_CURRENCY_BY_COUNTRY = {
    "ru": "RUB",
    "by": "BYN",
    "kz": "KZT",
    "kg": "KGS",
    "am": "AMD",
    "uz": "UZS",
    "ge": "GEL",
    "ab": "RUB",
}


def upgrade() -> None:
    """Add countries, country column and currency columns."""
    # 1. Create countries table
    op.create_table(
        "countries",
        sa.Column("code", sa.String(8), primary_key=True),
        sa.Column("name_native", sa.String, nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("currency_symbol", sa.String(10), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # 2. Seed countries
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO countries"
            " (code, name_native, currency_code, currency_symbol)"
            " VALUES (:code, :name_native, :currency_code, :currency_symbol)"
        ),
        [
            {
                "code": code,
                "name_native": name,
                "currency_code": cur,
                "currency_symbol": sym,
            }
            for code, name, cur, sym in _COUNTRIES
        ],
    )

    # 3. Add country to users (nullable)
    op.add_column(
        "users",
        sa.Column("country", sa.String, nullable=True),
    )

    # 4. Populate users.country from blogger_profiles.country
    for raw, code in _NORMALIZE.items():
        conn.execute(
            sa.text(
                "UPDATE users u"
                " SET country = :code"
                " FROM blogger_profiles bp"
                " WHERE bp.user_id = u.user_id"
                "   AND lower(bp.country) = :raw"
            ),
            {"code": code, "raw": raw},
        )

    # 5. Add currency to blogger_profiles
    op.add_column(
        "blogger_profiles",
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'RUB'"),
        ),
    )

    # 6. Populate blogger_profiles.currency via normalized country
    for raw, code in _NORMALIZE.items():
        currency = _CURRENCY_BY_COUNTRY.get(code, "RUB")
        conn.execute(
            sa.text(
                "UPDATE blogger_profiles SET currency = :cur"
                " WHERE lower(country) = :raw"
            ),
            {"cur": currency, "raw": raw},
        )

    # 7. Add currency to orders
    op.add_column(
        "orders",
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'RUB'"),
        ),
    )


def downgrade() -> None:
    """Remove country/currency columns and countries table."""
    op.drop_column("orders", "currency")
    op.drop_column("blogger_profiles", "currency")
    op.drop_column("users", "country")
    op.drop_table("countries")
