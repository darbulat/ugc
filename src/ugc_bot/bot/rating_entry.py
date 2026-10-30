"""Compact rating identities and owner-authorized order lists for bot entry."""

import base64
import binascii
from uuid import UUID

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.customer_intake import principal_for
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS

RATING_MENU = "customer:ratings"
RATING_ORDER = "bro:"
RATING_PARTICIPANT = "brp:"


def compact_id(value: UUID) -> str:
    return base64.urlsafe_b64encode(value.bytes).decode().rstrip("=")


def expand_id(value: str) -> UUID:
    try:
        if len(value) != 22:
            raise ValueError("rating_callback_invalid")
        result = UUID(
            bytes=base64.b64decode(value + "==", altchars=b"-_", validate=True)
        )
        if not result.int or compact_id(result) != value:
            raise ValueError("rating_callback_invalid")
        return result
    except (binascii.Error, TypeError) as exc:
        raise ValueError("rating_callback_invalid") from exc


def rating_text(locale, key):
    return DEFAULT_TEXTS.get(locale, DEFAULT_TEXTS["ru"])[key]


async def rating_user(incoming, roles):
    return await roles.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )


async def show_rating_orders(incoming, messenger, roles, orders, locale="ru"):
    user = await rating_user(incoming, roles)
    if user is None:
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=rating_text(locale, "msg_rating_work_required"),
        )
        return
    owned = await orders.list_by_advertiser(user.user_id)
    rows = [
        [
            Button(
                text=(
                    f"№{str(order.order_id).replace('-', '')[:8].upper()}"
                    f" — {order.offer_text[:45]}"
                ),
                callback_data=RATING_ORDER + compact_id(order.order_id),
            )
        ]
        for order in sorted(
            owned, key=lambda order: order.created_at, reverse=True
        )
    ]
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=rating_text(
            locale, "rating_choose_order" if rows else "rating_no_orders"
        ),
        keyboard=Keyboard(kind=KeyboardKind.INLINE, rows=rows)
        if rows
        else None,
    )


async def eligible_rating_participants(incoming, roles, ratings, order_id):
    user = await rating_user(incoming, roles)
    if user is None:
        raise PermissionError("rating_access_denied")
    participants = await ratings.list_for_order(
        user.user_id, order_id, principal=principal_for(incoming, user.user_id)
    )
    return [item for item in participants if item["rating_eligible"]]
