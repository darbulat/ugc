"""Manual customer cards show the selected slot and ordinary contact actions."""

from uuid import UUID

import pytest

from ugc_bot.application.services.invite_handoff_notices import (
    customer_contact_notice,
)


@pytest.mark.parametrize("ordinal,total", [(4, 10), (5, 10), (12, 200)])
@pytest.mark.parametrize("title", [None, "Сквош"])
def test_manual_contact_card_has_actual_position_and_regular_contact_buttons(
    ordinal, total, title
):
    order_id = UUID("ee331b1c-ffe7-57c6-8343-8eaa893212a3")
    text, markup = customer_contact_notice(
        {
            "order_id": order_id,
            "ordinal": ordinal,
            "bloggers_needed": total,
            "creator_name": "Мурат",
            "instagram": "murat.investor",
            "telegram": "dimitrovmurat",
            "complimentary": False,
            "creator_offer_card": {"title": title} if title else None,
        }
    )
    assert text == "\n".join(
        [
            "Креатор подтвердил интерес",
            "Сквош · UMC-EE331B1C" if title else "UMC-EE331B1C",
            f"Позиция №{ordinal} из {total}",
            "",
            "Мурат",
            "Instagram: https://instagram.com/murat.investor",
            "Telegram: @dimitrovmurat",
        ]
    )
    assert [
        (row[0].text, row[0].url) for row in markup.inline_keyboard[:2]
    ] == [
        ("Написать креатору", "https://t.me/dimitrovmurat"),
        ("Открыть профиль", "https://instagram.com/murat.investor"),
    ]
    assert markup.inline_keyboard[0][0].style == "primary"
    assert markup.inline_keyboard[-1][0].callback_data


def test_unnamed_preview_contact_keeps_profile_and_preview_summary():
    order_id = UUID(int=1)
    text, markup = customer_contact_notice(
        {
            "order_id": order_id,
            "ordinal": 2,
            "bloggers_needed": 2,
            "creator_name": None,
            "instagram": "outside_creator",
            "telegram": None,
            "complimentary": True,
        }
    )
    assert "\nКреатор\n" in text
    assert "Позиция №2 из 2" in text
    assert "Telegram:" not in text
    assert (
        markup.inline_keyboard[0][0].url
        == "https://instagram.com/outside_creator"
    )
    assert markup.inline_keyboard[-1][0].callback_data == f"ip:{order_id.hex}"
