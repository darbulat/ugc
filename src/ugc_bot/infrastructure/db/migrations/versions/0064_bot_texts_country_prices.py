"""Add country-specific price/budget texts to bot_texts."""

import sqlalchemy as sa
from alembic import op

revision = "0064_bot_texts_country_prices"
down_revision = "0063_country_locale"
branch_labels = None
depends_on = None

# Currency name in prepositional case (в чём?) per country code
_CURRENCY_LABEL = {
    "by": "белорусских рублях",
    "kz": "тенге",
    "kg": "сомах",
    "am": "драмах",
    "uz": "сумах",
    "ge": "лари",
}

# Keys whose Russian text mentions "в рублях" and needs per-country override
_TEXTS: list[tuple[str, str]] = [
    (
        "prompt_edit_price",
        "Укажите цену за 1 UGC\u2011видео в {currency}:",
    ),
    (
        "msg_step_ask_price",
        "Заказчики отбирают креаторов по бюджету —"
        " указанная цена ускоряет сделку."
        " Сколько стоит одно UGC\u2011видео?"
        " Цена в {currency},"
        " например: 500, 1000, 2000"
        "\n\nШаг 10 из 12",
    ),
    (
        "msg_order_budget",
        "Бюджет за 1 UGC-видео? Укажите цену в {currency}: 500, 1000, 2000",
    ),
]


def upgrade() -> None:
    """Insert country-specific price texts into bot_texts."""
    conn = op.get_bind()
    for country, currency in _CURRENCY_LABEL.items():
        for key, template in _TEXTS:
            value = template.format(currency=currency)
            conn.execute(
                sa.text(
                    "INSERT INTO bot_texts (key, locale, value) "
                    "VALUES (:key, :locale, :value) "
                    "ON CONFLICT (key, locale) DO UPDATE SET value = :value"
                ),
                {"key": key, "locale": country, "value": value},
            )


def downgrade() -> None:
    """Remove country-specific price texts from bot_texts."""
    conn = op.get_bind()
    for country in _CURRENCY_LABEL:
        for key, _ in _TEXTS:
            conn.execute(
                sa.text(
                    "DELETE FROM bot_texts"
                    " WHERE key = :key AND locale = :locale"
                ),
                {"key": key, "locale": country},
            )
