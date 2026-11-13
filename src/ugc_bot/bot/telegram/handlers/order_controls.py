"""Telegram buttons for order cancellation and payment support."""

from uuid import UUID

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.customer_actions import PAYMENT_SUPPORT_PREFIX
from ugc_bot.bot.texts.defaults.customer import customer_text

CANCEL_ORDER_PREFIX = "order:cancel:"
CONFIRM_CANCEL_ORDER_PREFIX = "order:cancel_yes:"
KEEP_ORDER = "order:keep"


def payment_help_button(
    order_id: UUID, locale: str, suffix: str = ""
) -> Button:
    return Button(
        text=customer_text(locale, "payment_help") + suffix,
        callback_data=f"{PAYMENT_SUPPORT_PREFIX}{order_id}",
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
