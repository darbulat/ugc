"""Telegram buttons for order cancellation and payment support."""

from urllib.parse import urlencode
from uuid import UUID

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.customer_actions import order_number
from ugc_bot.bot.texts.defaults.customer import customer_text

PAYMENT_SUPPORT_URL = "https://t.me/usemycontent"

CANCEL_ORDER_PREFIX = "order:cancel:"
CONFIRM_CANCEL_ORDER_PREFIX = "order:cancel_yes:"
KEEP_ORDER = "order:keep"


def payment_help_button(
    order_id: UUID, locale: str, suffix: str = ""
) -> Button:
    label = customer_text(locale, "payment_help")
    draft = urlencode({"text": f"{label} · №{order_number(order_id)}"})
    return Button(
        text=label + suffix,
        url=f"{PAYMENT_SUPPORT_URL}?{draft}",
    )


def payment_help_keyboard(order_id: UUID, locale: str) -> Keyboard:
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[payment_help_button(order_id, locale)]],
    )


def cancel_order_button(
    order_id: UUID, locale: str, suffix: str = ""
) -> Button:
    return Button(
        text=customer_text(locale, "order_cancel_button") + suffix,
        callback_data=f"{CANCEL_ORDER_PREFIX}{order_id}",
    )


def cancellation_confirmation(order_id: UUID, locale: str) -> Keyboard:
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=customer_text(locale, "order_cancel_button"),
                    callback_data=f"{CONFIRM_CANCEL_ORDER_PREFIX}{order_id}",
                ),
                Button(
                    text=customer_text(locale, "order_keep_button"),
                    callback_data=KEEP_ORDER,
                ),
            ]
        ],
    )
