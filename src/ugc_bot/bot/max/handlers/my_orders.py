"""Max messenger my orders handlers.

Differences from Telegram:
- No "Pay" button (no payment invoice on Max).
- Pagination works the same via inline callbacks.
"""

from typing import Any

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_PROFILE_AGREE,
    CALLBACK_PROFILE_MENU_MY_ORDERS,
    PAY_ORDER_CALLBACK_PREFIX,
    confirm_agreement_inline_keyboard,
)
from ugc_bot.bot.telegram.handlers.my_orders import (
    MY_ORDERS_TEXTS_KEYS,
    _build_currency_map,
    _render_blogger_orders_page,
    _render_page,
)
from ugc_bot.bot.telegram.handlers.profile import (
    _ADVERTISER_AGREEMENTS_STATE,
    _BLOGGER_AGREEMENTS_STATE,
)
from ugc_bot.bot.telegram.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
)

router = MaxRouter()

_MY_ORDERS_CALLBACK_PREFIX = "my_orders:"
_MY_ORDERS_BLOGGER_CALLBACK_PREFIX = "my_orders_blogger:"


def _strip_pay_buttons(keyboard: Keyboard) -> Keyboard | None:
    """Return a copy without pay buttons, or None when no buttons remain."""
    filtered_rows = [
        [
            btn
            for btn in row
            if not (
                btn.callback_data
                and btn.callback_data.startswith(PAY_ORDER_CALLBACK_PREFIX)
            )
        ]
        for row in keyboard.rows
    ]
    # Drop empty rows produced by filtering
    filtered_rows = [row for row in filtered_rows if row]
    return (
        Keyboard(kind=KeyboardKind.INLINE, rows=filtered_rows)
        if filtered_rows
        else None
    )


async def _send_advertiser_orders(
    incoming: IncomingMessage | IncomingCallback,
    user_id: Any,
    messenger_client: Any,
    order_service: Any,
    offer_response_service: Any,
    bot_texts_service: Any,
    currency_map: dict,
    order_texts: dict,
    currency_symbol: str,
    locale: str,
) -> None:
    """Render and send advertiser order list (page 1) without pay buttons."""
    orders = sorted(
        await order_service.list_by_advertiser(user_id),
        key=lambda item: item.created_at,
        reverse=True,
    )
    if orders:
        text, keyboard = await _render_page(
            orders,
            page=1,
            offer_response_service=offer_response_service,
            currency_map=currency_map,
            default_currency_symbol=currency_symbol,
            texts=order_texts,
        )
        keyboard_without_pay = _strip_pay_buttons(keyboard)
        await messenger_client.send_text(
            chat_id=incoming.chat_id, text=text, keyboard=keyboard_without_pay
        )
    else:
        msg_no_orders = await bot_texts_service.get("msg_no_orders", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_no_orders,
        )


async def _send_blogger_orders(
    incoming: IncomingMessage | IncomingCallback,
    user_id: Any,
    messenger_client: Any,
    order_service: Any,
    offer_response_service: Any,
    bot_texts_service: Any,
    currency_map: dict,
    order_texts: dict,
    currency_symbol: str,
    locale: str,
) -> None:
    """Render and send blogger order list (page 1)."""
    responses = await offer_response_service.list_by_blogger(
        user_id, in_offer_only=True
    )
    order_responses = []
    for resp in sorted(
        responses,
        key=lambda r: (r.updated_at or r.created_at, r.created_at),
        reverse=True,
    ):
        order = await order_service.get_order(resp.order_id)
        if order is not None:
            order_responses.append((order, resp))
    if order_responses:
        text, keyboard = _render_blogger_orders_page(
            order_responses,
            page=1,
            currency_map=currency_map,
            default_currency_symbol=currency_symbol,
            texts=order_texts,
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id, text=text, keyboard=keyboard
        )
    else:
        msg_no_blogger = await bot_texts_service.get(
            "msg_no_blogger_orders", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_no_blogger,
        )


async def _send_my_orders_content(
    incoming: IncomingMessage | IncomingCallback,
    deps: dict[str, Any],
) -> None:
    """Send fill profile, agreement, or order lists depending on user state."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    order_service = deps["order_service"]
    offer_response_service = deps["offer_response_service"]
    profile_service = deps["profile_service"]
    user_role_service = deps["user_role_service"]
    state_store = deps["state_store"]
    config = deps["config"]
    country_repo = deps.get("country_repo")
    locale = deps.get("locale", "ru")

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    if user is None:
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    blogger = await profile_service.get_blogger_profile(user.user_id)

    if advertiser is None and blogger is None:
        msg_fill = await bot_texts_service.get(
            "msg_fill_profile_orders", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_fill,
        )
        return

    agreement_confirmed_at = (
        blogger.agreement_confirmed_at if blogger is not None else None
    ) or (advertiser.agreement_confirmed_at if advertiser is not None else None)

    if agreement_confirmed_at is None:
        agree_keys = [
            "btn_confirm_agreement",
            "msg_confirm_agreement",
            "msg_agreements_intro_default",
            "msg_label_offer",
            "msg_label_privacy",
            "msg_label_consent",
            "msg_confirm_docs_fallback",
        ]
        agree_texts = await bot_texts_service.get_many(agree_keys, locale)
        agreements_text = format_agreements_message(
            config,
            intro=agree_texts.get("msg_confirm_agreement"),
            texts=agree_texts,
            country_code=getattr(user, "country", None),
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=agreements_text,
            keyboard=confirm_agreement_inline_keyboard(
                CALLBACK_PROFILE_AGREE, agree_texts
            ),
            parse_mode="HTML",
        )
        await state_store.update_data(user_id=str(user.user_id))
        if blogger is not None:
            await state_store.set_state(_BLOGGER_AGREEMENTS_STATE)
        else:
            await state_store.set_state(_ADVERTISER_AGREEMENTS_STATE)
        return

    currency_map = await _build_currency_map(country_repo)
    order_texts = await bot_texts_service.get_many(
        list(MY_ORDERS_TEXTS_KEYS), locale
    )
    currency_symbol = config.market.currency_symbol

    if advertiser is not None:
        await _send_advertiser_orders(
            incoming,
            user.user_id,
            messenger_client,
            order_service,
            offer_response_service,
            bot_texts_service,
            currency_map,
            order_texts,
            currency_symbol,
            locale,
        )

    if blogger is not None:
        await _send_blogger_orders(
            incoming,
            user.user_id,
            messenger_client,
            order_service,
            offer_response_service,
            bot_texts_service,
            currency_map,
            order_texts,
            currency_symbol,
            locale,
        )


@router.message(lambda m: bool(m.text and m.text.strip() == "/my_orders"))
async def show_my_orders(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Show advertiser and blogger orders."""
    messenger_client = deps["messenger_client"]
    user_role_service = deps["user_role_service"]
    bot_texts_service = deps["bot_texts_service"]
    locale = deps.get("locale", "ru")

    order_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_my_orders_blocked",
            "msg_my_orders_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=order_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=order_msgs.get("msg_my_orders_blocked", ""),
        pause_msg=order_msgs.get("msg_my_orders_pause", ""),
    )
    if user is None:
        return

    await _send_my_orders_content(incoming, deps)


@router.callback(lambda c: c.data == CALLBACK_PROFILE_MENU_MY_ORDERS)
async def show_my_orders_from_profile_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Show my orders from profile inline menu."""
    messenger_client = deps["messenger_client"]
    user_role_service = deps["user_role_service"]
    bot_texts_service = deps["bot_texts_service"]
    locale = deps.get("locale", "ru")

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    order_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_my_orders_blocked",
            "msg_my_orders_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=order_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=order_msgs.get("msg_my_orders_blocked", ""),
        pause_msg=order_msgs.get("msg_my_orders_pause", ""),
    )
    if user is None:
        return

    # Use a fake IncomingMessage so _send_my_orders_content can use .user
    fake_msg = IncomingMessage(
        chat_id=incoming.chat_id,
        user=incoming.user,
        text=None,
        message_id=incoming.message_id,
    )
    await _send_my_orders_content(fake_msg, deps)


@router.callback(
    lambda c: bool(
        c.data
        and (
            c.data.startswith(_MY_ORDERS_CALLBACK_PREFIX)
            or c.data.startswith(_MY_ORDERS_BLOGGER_CALLBACK_PREFIX)
        )
    )
)
async def paginate_orders(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Handle pagination for advertiser and blogger orders."""
    messenger_client = deps["messenger_client"]
    user_role_service = deps["user_role_service"]
    bot_texts_service = deps["bot_texts_service"]
    order_service = deps["order_service"]
    offer_response_service = deps["offer_response_service"]
    profile_service = deps["profile_service"]
    config = deps["config"]
    country_repo = deps.get("country_repo")
    locale = deps.get("locale", "ru")

    order_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_my_orders_blocked",
            "msg_my_orders_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=order_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=order_msgs.get("msg_my_orders_blocked", ""),
        pause_msg=order_msgs.get("msg_my_orders_pause", ""),
    )
    if user is None:
        return

    currency_map = await _build_currency_map(country_repo)
    order_texts = await bot_texts_service.get_many(
        list(MY_ORDERS_TEXTS_KEYS), locale
    )

    data = incoming.data or ""
    keyboard_to_edit: Keyboard | None = None
    if data.startswith(_MY_ORDERS_BLOGGER_CALLBACK_PREFIX):
        raw = data.split(_MY_ORDERS_BLOGGER_CALLBACK_PREFIX, 1)[-1]
        blogger = await profile_service.get_blogger_profile(user.user_id)
        if blogger is None:
            msg = await bot_texts_service.get(
                "msg_blogger_profile_empty", locale
            )
            await messenger_client.answer_callback(
                callback_id=incoming.callback_id,
                text=msg,
            )
            return
        try:
            page = int(raw)
        except ValueError:
            page = 1
        responses = await offer_response_service.list_by_blogger(
            user.user_id, in_offer_only=True
        )
        order_responses = []
        for resp in sorted(
            responses,
            key=lambda r: (r.updated_at or r.created_at, r.created_at),
            reverse=True,
        ):
            order = await order_service.get_order(resp.order_id)
            if order is not None:
                order_responses.append((order, resp))
        text, keyboard = _render_blogger_orders_page(
            order_responses,
            page=page,
            currency_map=currency_map,
            default_currency_symbol=config.market.currency_symbol,
            texts=order_texts,
        )
        keyboard_to_edit = keyboard
    else:
        raw = data.split(_MY_ORDERS_CALLBACK_PREFIX, 1)[-1]
        advertiser = await profile_service.get_advertiser_profile(user.user_id)
        if advertiser is None:
            msg = await bot_texts_service.get(
                "msg_advertiser_profile_empty", locale
            )
            await messenger_client.answer_callback(
                callback_id=incoming.callback_id,
                text=msg,
            )
            return
        try:
            page = int(raw)
        except ValueError:
            page = 1
        orders = sorted(
            await order_service.list_by_advertiser(user.user_id),
            key=lambda item: item.created_at,
            reverse=True,
        )
        text, keyboard = await _render_page(
            orders,
            page=page,
            offer_response_service=offer_response_service,
            currency_map=currency_map,
            default_currency_symbol=config.market.currency_symbol,
            texts=order_texts,
        )
        keyboard_to_edit = _strip_pay_buttons(keyboard)

    if incoming.message_id:
        await messenger_client.edit_text(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            text=text,
            keyboard=keyboard_to_edit,
        )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
