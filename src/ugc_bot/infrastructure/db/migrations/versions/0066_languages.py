"""Add languages table, users.language; drop countries.locale."""

import sqlalchemy as sa
from alembic import op

revision = "0066_languages"
down_revision = "0065_agreement_confirmed_at_profiles"
branch_labels = None
depends_on = None

_COUNTRY_LOCALE_KEYS = ("by", "kz", "kg", "am", "uz", "ge")
_PRICE_TEXT_KEYS = (
    "prompt_edit_price",
    "msg_step_ask_price",
    "msg_order_budget",
)


def upgrade() -> None:
    """Create languages table, add users.language, drop countries.locale."""
    # 1. Create languages table
    op.create_table(
        "languages",
        sa.Column("code", sa.String(10), primary_key=True),
        sa.Column("name_native", sa.String(64), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # 2. Seed initial languages from distinct countries.locale values
    conn = op.get_bind()
    seed = [
        ("ru", "Русский"),
        ("en", "English"),
    ]
    seen: set[str] = {code for code, _ in seed}
    for code, name in seed:
        conn.execute(
            sa.text(
                "INSERT INTO languages (code, name_native, enabled) "
                "VALUES (:code, :name, true) ON CONFLICT DO NOTHING"
            ),
            {"code": code, "name": name},
        )
    # Insert any extra locales found in countries that weren't in seed
    rows = conn.execute(
        sa.text("SELECT DISTINCT locale FROM countries")
    ).fetchall()
    for (locale,) in rows:
        if locale and locale not in seen:
            conn.execute(
                sa.text(
                    "INSERT INTO languages (code, name_native, enabled) "
                    "VALUES (:code, :name, true) ON CONFLICT DO NOTHING"
                ),
                {"code": locale, "name": locale},
            )
            seen.add(locale)

    # 3. Add users.language column
    op.add_column(
        "users",
        sa.Column("language", sa.String(10), nullable=True),
    )

    # 4. Populate users.language from countries.locale
    conn.execute(
        sa.text(
            "UPDATE users "
            "SET language = countries.locale "
            "FROM countries "
            "WHERE users.country = countries.code"
        )
    )

    # 5. Drop countries.locale column
    op.drop_column("countries", "locale")

    # 6. Delete country-code bot_texts overrides (hacks from migration 0064)
    for locale in _COUNTRY_LOCALE_KEYS:
        for key in _PRICE_TEXT_KEYS:
            conn.execute(
                sa.text(
                    "DELETE FROM bot_texts "
                    "WHERE key = :key AND locale = :locale"
                ),
                {"key": key, "locale": locale},
            )


def downgrade() -> None:
    """Reverse migration."""
    # Re-add countries.locale (default 'ru')
    op.add_column(
        "countries",
        sa.Column(
            "locale",
            sa.String(8),
            nullable=False,
            server_default=sa.text("'ru'"),
        ),
    )

    # Drop users.language
    op.drop_column("users", "language")

    # Drop languages table
    op.drop_table("languages")
