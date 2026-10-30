"""MAX customer rating entry into the signed order-specific Mini App."""

from typing import Any

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.rating_entry import (
    RATING_MENU,
    RATING_ORDER,
    eligible_rating_participants,
    expand_id,
    rating_text,
    show_rating_orders,
)

router = MaxRouter()


@router.message(
    lambda incoming: (incoming.text or "").split(" ", 1)[0] == "/rate_order"
)
async def rating_orders_command(incoming, deps: dict[str, Any]) -> None:
    await show_rating_orders(
        incoming,
        deps["messenger_client"],
        deps["user_role_service"],
        deps["order_service"],
        deps.get("locale", "ru"),
    )


@router.callback(lambda incoming: incoming.data == RATING_MENU)
async def rating_orders_callback(incoming, deps: dict[str, Any]) -> None:
    await deps["messenger_client"].answer_callback(
        callback_id=incoming.callback_id
    )
    await rating_orders_command(incoming, deps)


@router.callback(
    lambda incoming: bool(
        incoming.data and incoming.data.startswith(RATING_ORDER)
    )
)
async def rating_order_callback(incoming, deps: dict[str, Any]) -> None:
    messenger = deps["messenger_client"]
    locale = deps.get("locale", "ru")
    await messenger.answer_callback(callback_id=incoming.callback_id)
    try:
        order_id = expand_id((incoming.data or "")[len(RATING_ORDER) :])
        participants = await eligible_rating_participants(
            incoming,
            deps["user_role_service"],
            deps["blogger_rating_service"],
            order_id,
        )
        if not participants:
            await messenger.send_text(
                chat_id=incoming.chat_id,
                text=rating_text(locale, "rating_no_completed"),
            )
            return
        base = deps["config"].webhook.webhook_base_url.strip().rstrip("/")
        if not base:
            raise ValueError("rating_app_unavailable")
    except (ValueError, PermissionError):
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=rating_text(locale, "msg_rating_work_required"),
        )
        return
    url = f"{base}/miniapp/max_app.html?screen=ratings&order_id={order_id}"
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=rating_text(locale, "rating_open_app_prompt"),
        keyboard=Keyboard(
            kind=KeyboardKind.INLINE,
            rows=[
                [
                    Button(
                        text=rating_text(locale, "rating_open_app"),
                        web_app_url=url,
                    )
                ]
            ],
        ),
    )
