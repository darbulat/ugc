"""Add locale column to countries table."""

import sqlalchemy as sa
from alembic import op

revision = "0063_country_locale"
down_revision = "0062_country_currency"
branch_labels = None
depends_on = None

# Locale per country code; all CIS/Russian-speaking countries → "ru"
_COUNTRY_LOCALES = {
    "ru": "ru",
    "by": "ru",
    "kz": "ru",
    "kg": "ru",
    "am": "ru",
    "uz": "ru",
    "ab": "ru",
    "ge": "en",
}


def upgrade() -> None:
    """Add locale column to countries with appropriate defaults."""
    op.add_column(
        "countries",
        sa.Column(
            "locale",
            sa.String(8),
            nullable=False,
            server_default=sa.text("'ru'"),
        ),
    )
    conn = op.get_bind()
    for code, locale in _COUNTRY_LOCALES.items():
        conn.execute(
            sa.text("UPDATE countries SET locale = :locale WHERE code = :code"),
            {"locale": locale, "code": code},
        )


def downgrade() -> None:
    """Remove locale column from countries."""
    op.drop_column("countries", "locale")
