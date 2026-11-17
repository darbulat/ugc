"""Render admin-only offer previews without production response callbacks."""

from dataclasses import replace
from html import escape

from ugc_bot.application.creator_offer_cards import (
    CALLBACK_PREFIX,
    SKIP_REASONS,
    VIEWS,
    OfferCard,
    render_public_offer,
    render_saved_offer,
    reward,
)
from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.domain.entities import Order

PREVIEW_CALLBACK_PREFIX = "offer_preview:"
PREVIEW_ACTIONS = VIEWS | {"done"} | {f"s_{key}" for key in SKIP_REASONS}


def _back(order: Order, ru: bool) -> Button:
    return Button(
        "← К офферу" if ru else "← Back",
        callback_data=f"{PREVIEW_CALLBACK_PREFIX}open:{order.order_id}",
    )


def _result(order: Order, locale: str, accepted: bool, ru: bool) -> OfferCard:
    title = (
        ("Тестовый отклик подтверждён" if accepted else "Тестовый пропуск")
        if ru
        else ("Test response confirmed" if accepted else "Test skip")
    )
    notice = (
        "Реальный отклик не создан. Заказ и рассылка не изменены."
        if ru
        else "No real response was created. "
        "The order and dispatch are unchanged."
    )
    saved = render_saved_offer(order, locale) if accepted else None
    rows = list(saved.keyboard.rows) if saved and saved.keyboard else []
    rows.append([_back(order, ru)])
    name = (order.creator_offer_card or {}).get("title", "")
    text = (
        f"<b>{title}</b>\n\n{escape(name)} · "
        f"{escape(reward(order, ru))}\n\n{notice}"
    )
    return OfferCard(text, Keyboard(KeyboardKind.INLINE, rows))


def render_offer_preview(
    order: Order, locale: str, view: str = "open"
) -> OfferCard:
    """Reuse the real card, replacing every response callback namespace."""
    if view not in PREVIEW_ACTIONS:
        raise ValueError("Unknown preview action")
    ru = locale.lower().replace("_", "-").split("-", 1)[0] == "ru"
    card = render_public_offer(order, locale, view if view in VIEWS else "open")
    if view == "done" or view.startswith("s_"):
        return _result(order, locale, view == "done", ru)
    labels = {
        "confirm": "Откликнуться · тест" if ru else "Respond · test",
        "done": "Подтвердить тест" if ru else "Confirm test",
    }
    rows = []
    for row in card.keyboard.rows if card.keyboard else []:
        rewritten = []
        for button in row:
            data = button.callback_data
            if data and data.startswith(CALLBACK_PREFIX):
                action = data.removeprefix(CALLBACK_PREFIX).partition(":")[0]
                button = replace(
                    button,
                    text=labels.get(action, button.text),
                    callback_data=data.replace(
                        CALLBACK_PREFIX, PREVIEW_CALLBACK_PREFIX, 1
                    ),
                )
            rewritten.append(button)
        rows.append(rewritten)
    text = card.text
    if view == "confirm":
        title = "Тестовый отклик" if ru else "Test response"
        notice = (
            "Это предпросмотр. Реальный отклик не будет создан, "
            "контакты и уведомления никому не отправятся."
            if ru
            else "This is a preview. No real response, contact delivery "
            "or notification will be created."
        )
        text = f"<b>{title}</b>\n\n{escape(reward(order, ru))}\n\n{notice}"
    return OfferCard(text, Keyboard(KeyboardKind.INLINE, rows))
