"""Drop unused countries.locale column."""

import sqlalchemy as sa
from alembic import op

revision = "0075_drop_countries_locale"
down_revision = "0074_restore_countries_locale"
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


def upgrade() -> None:
    """Drop countries.locale — locale is stored per-user in users.language."""
    op.drop_column("countries", "locale")


def downgrade() -> None:
    """Restore countries.locale with original backfill values."""
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
