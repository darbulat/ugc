"""Restore countries.locale column to match current ORM model."""

import sqlalchemy as sa
from alembic import op

revision = "0074_restore_countries_locale"
down_revision = "0073_backfill_referral_income"
branch_labels = None
depends_on = None

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


def _countries_has_locale(conn: sa.Connection) -> bool:
    """Return True when countries.locale already exists."""
    inspector = sa.inspect(conn)
    columns = inspector.get_columns("countries")
    return any(column["name"] == "locale" for column in columns)


def upgrade() -> None:
    """Add countries.locale back and backfill values by country code."""
    conn = op.get_bind()
    if _countries_has_locale(conn):
        return

    op.add_column(
        "countries",
        sa.Column(
            "locale",
            sa.String(8),
            nullable=False,
            server_default=sa.text("'ru'"),
        ),
    )

    for code, locale in _COUNTRY_LOCALES.items():
        conn.execute(
            sa.text("UPDATE countries SET locale = :locale WHERE code = :code"),
            {"locale": locale, "code": code},
        )


def downgrade() -> None:
    """Drop countries.locale if present."""
    conn = op.get_bind()
    if not _countries_has_locale(conn):
        return
    op.drop_column("countries", "locale")
