"""Max messenger order creation flow handlers.

Differences from Telegram:
- No photo upload step (photo=None always).
- No payment invoice at the end — sends confirmation text only.
"""

import logging
from typing import Any, cast

from ugc_bot.application.messenger.dto import IncomingCallback, IncomingMessage
from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_order_created,
    notify_support_chat_about_new_order,
)
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_ORDER_AGREE,
    CALLBACK_PROFILE_MENU_CREATE_ORDER,
    confirm_agreement_inline_keyboard,
    flow_inline_keyboard,
    flow_keyboard_remove,
)
from ugc_bot.bot.telegram.handlers.order_creation_states import (
    CALLBACK_ORDER_BLOGGERS_PREFIX,
    CALLBACK_ORDER_CONTENT_ADS,
    CALLBACK_ORDER_CONTENT_BOTH,
    CALLBACK_ORDER_CONTENT_SOCIAL,
    CALLBACK_ORDER_COOP_BARTER,
    CALLBACK_ORDER_COOP_BOTH,
    CALLBACK_ORDER_COOP_PAYMENT,
    CALLBACK_ORDER_DEADLINES_PREFIX,
    CALLBACK_ORDER_TYPE_PLACEMENT,
    CALLBACK_ORDER_TYPE_UGC,
    CONTENT_USAGE_ADS,
    CONTENT_USAGE_BOTH,
    CONTENT_USAGE_SOCIAL,
    CONTENT_USAGE_TO_OFFER,
    COOP_BARTER,
    COOP_BOTH,
    COOP_PAYMENT,
    DEADLINES_3,
    DEADLINES_7,
    DEADLINES_14,
    DEADLINES_TO_OFFER,
    ORDER_TYPE_UGC_ONLY,
    ORDER_TYPE_UGC_PLUS_PLACEMENT,
    OrderCreationStates,
    bloggers_needed_keyboard,
    content_usage_keyboard,
    cooperation_format_keyboard,
    deadlines_keyboard,
    order_type_keyboard,
)
from ugc_bot.bot.telegram.handlers.profile import _ADVERTISER_AGREEMENTS_STATE
from ugc_bot.bot.telegram.handlers.security_warnings import (
    ORDER_CREATED_MESSAGE,
)
from ugc_bot.bot.telegram.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
    parse_user_id_from_state,
)
from ugc_bot.bot.telegram.validators import (
    VALIDATOR_ERR_KEYS,
    normalize_url,
    validate_barter_description,
    validate_geography,
    validate_offer_text,
    validate_price,
    validate_product_link,
)
from ugc_bot.domain.enums import OrderType

router = MaxRouter()
logger = logging.getLogger(__name__)

# FSM state name constants used by message_in_state / callback_in_state.
# These are always defined as non-None strings at runtime; cast to str for mypy.
_STATE_ORDER_TYPE = cast(str, OrderCreationStates.order_type.state)
_STATE_OFFER_TEXT = cast(str, OrderCreationStates.offer_text.state)
_STATE_COOPERATION = cast(str, OrderCreationStates.cooperation_format.state)
_STATE_PRICE = cast(str, OrderCreationStates.price.state)
_STATE_BARTER = cast(str, OrderCreationStates.barter_description.state)
_STATE_BLOGGERS = cast(str, OrderCreationStates.bloggers_needed.state)
_STATE_PRODUCT_LINK = cast(str, OrderCreationStates.product_link.state)
_STATE_CONTENT_USAGE = cast(str, OrderCreationStates.content_usage.state)
_STATE_DEADLINES = cast(str, OrderCreationStates.deadlines.state)
_STATE_GEOGRAPHY = cast(str, OrderCreationStates.geography.state)


def _parse_bloggers_callback_data(data: str) -> int | None:
    """Parse bloggers count from callback_data order:bloggers:N."""
    if not data or not data.startswith(CALLBACK_ORDER_BLOGGERS_PREFIX):
        return None
    try:
        return int(data[len(CALLBACK_ORDER_BLOGGERS_PREFIX) :])
    except ValueError:
        return None


def _deadlines_label_from_callback(data: str) -> str | None:
    """Return display label for a deadlines callback (e.g. '⏱ До 3 дней')."""
    if not data or not data.startswith(CALLBACK_ORDER_DEADLINES_PREFIX):
        return None
    suffix = data[len(CALLBACK_ORDER_DEADLINES_PREFIX) :]
    return {
        "3": DEADLINES_3,
        "7": DEADLINES_7,
        "14": DEADLINES_14,
    }.get(suffix)


def _deadlines_offer_from_callback(data: str) -> str | None:
    """Map deadlines callback_data to offer text."""
    key = _deadlines_label_from_callback(data)
    return DEADLINES_TO_OFFER.get(key) if key else None


def _content_usage_from_callback(data: str) -> str | None:
    """Map content usage callback to offer text."""
    return {
        CALLBACK_ORDER_CONTENT_SOCIAL: CONTENT_USAGE_TO_OFFER[
            CONTENT_USAGE_SOCIAL
        ],
        CALLBACK_ORDER_CONTENT_ADS: CONTENT_USAGE_TO_OFFER[CONTENT_USAGE_ADS],
        CALLBACK_ORDER_CONTENT_BOTH: CONTENT_USAGE_TO_OFFER[CONTENT_USAGE_BOTH],
    }.get(data)


async def _start_order_flow(
    incoming: IncomingMessage,
    deps: dict,
) -> None:
    """Check advertiser profile + agreement, then show order type keyboard."""
    messenger_client = deps["messenger_client"]
    user_role_service = deps["user_role_service"]
    profile_service = deps["profile_service"]
    bot_texts_service = deps["bot_texts_service"]
    config = deps["config"]
    state_store = deps["state_store"]

    locale = deps.get("locale", "ru")
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_order_creation_blocked",
            "msg_order_creation_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=allow_msgs.get("msg_order_creation_blocked", ""),
        pause_msg=allow_msgs.get("msg_order_creation_pause", ""),
    )
    if user is None:
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is None:
        msg_fill = await bot_texts_service.get(
            "msg_advertiser_profile_fill", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_fill,
        )
        return

    agreement_confirmed_at = getattr(advertiser, "agreement_confirmed_at", None)
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
            country_code=user.country,
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=agreements_text,
            keyboard=confirm_agreement_inline_keyboard(
                CALLBACK_ORDER_AGREE, agree_texts
            ),
            parse_mode="HTML",
        )
        await state_store.update_data(
            user_id=str(user.user_id), flow_type="order_creation"
        )
        await state_store.set_state(_ADVERTISER_AGREEMENTS_STATE)
        return

    await state_store.update_data(user_id=str(user.user_id))
    order_type_texts = await bot_texts_service.get_many(
        ["order_type_ugc_only", "order_type_ugc_placement"], locale
    )
    msg_what_need = await bot_texts_service.get("msg_what_do_you_need", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_what_need,
        keyboard=flow_inline_keyboard(
            rows=order_type_keyboard(order_type_texts)
        ),
    )
    await state_store.set_state(_STATE_ORDER_TYPE)


@router.message(lambda m: bool(m.text and m.text.strip() == "/create_order"))
async def start_order_creation(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Start order creation flow from /create_order command."""
    await _start_order_flow(incoming, deps)


@router.callback(lambda c: c.data == CALLBACK_PROFILE_MENU_CREATE_ORDER)
async def start_order_creation_from_profile_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Start order creation from profile inline menu callback."""
    messenger_client = deps["messenger_client"]
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    # Convert to IncomingMessage-compatible object for _start_order_flow.
    fake_message = IncomingMessage(
        chat_id=incoming.chat_id,
        user=incoming.user,
        text=None,
        message_id=incoming.message_id,
    )
    await _start_order_flow(fake_message, deps)


@router.callback(lambda c: c.data == CALLBACK_ORDER_AGREE)
async def handle_order_agree_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Confirm agreement in order creation flow and show order type."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    advertiser_registration_service = deps["advertiser_registration_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    current = await state_store.get_state()
    if current != _ADVERTISER_AGREEMENTS_STATE:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return

    data = await state_store.get_data()
    if data.get("flow_type") != "order_creation":
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return

    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        msg_expired = await bot_texts_service.get(
            "msg_session_expired_orders", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        await state_store.clear()
        return

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await advertiser_registration_service.confirm_advertiser_agreement(
        user_id=user_id,
    )
    await state_store.update_data(flow_type=None)

    order_type_texts = await bot_texts_service.get_many(
        ["order_type_ugc_only", "order_type_ugc_placement"], locale
    )
    msg_what = await bot_texts_service.get("msg_what_do_you_need", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_what,
        keyboard=flow_inline_keyboard(
            rows=order_type_keyboard(order_type_texts)
        ),
    )
    await state_store.set_state(_STATE_ORDER_TYPE)


@router.callback_in_state(
    _STATE_ORDER_TYPE,
    lambda c: (
        c.data in (CALLBACK_ORDER_TYPE_UGC, CALLBACK_ORDER_TYPE_PLACEMENT)
    ),
)
async def handle_order_type_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Store order type from inline and ask offer text."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    data = incoming.data or ""
    if data == CALLBACK_ORDER_TYPE_UGC:
        order_type = OrderType.UGC_ONLY
    elif data == CALLBACK_ORDER_TYPE_PLACEMENT:
        order_type = OrderType.UGC_PLUS_PLACEMENT
    else:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await state_store.update_data(order_type=order_type.value)

    msg_task = await bot_texts_service.get("msg_order_task_description", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_task,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(_STATE_OFFER_TEXT)


@router.message_in_state(_STATE_ORDER_TYPE)
async def handle_order_type_text(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle order type text and ask offer text."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    text = (incoming.text or "").strip()
    if text == ORDER_TYPE_UGC_ONLY:
        order_type = OrderType.UGC_ONLY
    elif text == ORDER_TYPE_UGC_PLUS_PLACEMENT:
        order_type = OrderType.UGC_PLUS_PLACEMENT
    else:
        order_type_texts = await bot_texts_service.get_many(
            ["order_type_ugc_only", "order_type_ugc_placement"], locale
        )
        msg_choose = await bot_texts_service.get(
            "msg_choose_from_keyboard", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_choose,
            keyboard=flow_inline_keyboard(
                rows=order_type_keyboard(order_type_texts)
            ),
        )
        return

    await state_store.update_data(order_type=order_type.value)
    msg_task = await bot_texts_service.get("msg_order_task_description", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_task,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(_STATE_OFFER_TEXT)


@router.message_in_state(_STATE_OFFER_TEXT)
async def handle_offer_text(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle offer text and ask cooperation format."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    offer_text = (incoming.text or "").strip()
    err = validate_offer_text(offer_text, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(offer_text=offer_text)
    coop_texts = await bot_texts_service.get_many(
        ["coop_barter", "coop_payment", "coop_both"], locale
    )
    msg_coop = await bot_texts_service.get("msg_coop_format", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_coop,
        keyboard=flow_inline_keyboard(
            rows=cooperation_format_keyboard(coop_texts)
        ),
    )
    await state_store.set_state(_STATE_COOPERATION)


async def _ask_price_or_barter_after_coop(
    incoming: IncomingMessage | IncomingCallback,
    canonical: str,
    deps: dict,
) -> None:
    """Send the right follow-up prompt depending on cooperation format."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")
    config = deps["config"]

    currency_symbol = config.market.currency_symbol
    msg_budget = (
        await bot_texts_service.get("msg_order_budget", locale)
    ).format(currency=currency_symbol)
    msg_barter = await bot_texts_service.get("msg_order_barter_ask", locale)

    if canonical == COOP_PAYMENT:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_budget,
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(_STATE_PRICE)
    elif canonical == COOP_BARTER:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_barter,
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(_STATE_BARTER)
    else:
        # COOP_BOTH: ask price first, then barter
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_budget,
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(_STATE_PRICE)


@router.callback_in_state(
    _STATE_COOPERATION,
    lambda c: (
        c.data
        in (
            CALLBACK_ORDER_COOP_BARTER,
            CALLBACK_ORDER_COOP_PAYMENT,
            CALLBACK_ORDER_COOP_BOTH,
        )
    ),
)
async def handle_cooperation_format_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Store cooperation format from inline and ask price/barter."""
    messenger_client = deps["messenger_client"]
    state_store = deps["state_store"]

    coop_map = {
        CALLBACK_ORDER_COOP_BARTER: COOP_BARTER,
        CALLBACK_ORDER_COOP_PAYMENT: COOP_PAYMENT,
        CALLBACK_ORDER_COOP_BOTH: COOP_BOTH,
    }
    data = incoming.data or ""
    canonical = coop_map.get(data)
    if canonical is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await state_store.update_data(cooperation_format=canonical)

    fake_msg = IncomingMessage(
        chat_id=incoming.chat_id,
        user=incoming.user,
        text=None,
        message_id=incoming.message_id,
    )
    await _ask_price_or_barter_after_coop(fake_msg, canonical, deps)


@router.message_in_state(_STATE_COOPERATION)
async def handle_cooperation_format_text(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle cooperation format from text message."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    text = (incoming.text or "").strip()
    if text not in (COOP_BARTER, COOP_PAYMENT, COOP_BOTH):
        coop_texts = await bot_texts_service.get_many(
            ["coop_barter", "coop_payment", "coop_both"], locale
        )
        msg_choose = await bot_texts_service.get(
            "msg_choose_from_keyboard", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_choose,
            keyboard=flow_inline_keyboard(
                rows=cooperation_format_keyboard(coop_texts)
            ),
        )
        return

    await state_store.update_data(cooperation_format=text)
    await _ask_price_or_barter_after_coop(incoming, text, deps)


@router.message_in_state(_STATE_PRICE)
async def handle_price(incoming: IncomingMessage, deps: dict[str, Any]) -> None:
    """Handle price and optionally ask barter description."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    config = deps["config"]
    locale = deps.get("locale", "ru")

    max_order_price = getattr(config.market, "max_order_price", 1_000_000.0)
    currency_symbol = config.market.currency_symbol

    raw = (incoming.text or "").replace(",", ".").strip()
    try:
        price = float(raw)
    except ValueError:
        msg_enter = await bot_texts_service.get("msg_enter_number", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id, text=msg_enter
        )
        return

    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    err = validate_price(
        price, max_order_price, currency_symbol, texts=validator_texts
    )
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(price=price)
    data = await state_store.get_data()

    allowed_blogger_counts = deps.get(
        "allowed_blogger_counts", frozenset({1, 3, 5})
    )
    msg_barter = await bot_texts_service.get("msg_order_barter_ask", locale)
    msg_how_many = await bot_texts_service.get("msg_how_many_creators", locale)

    if data.get("cooperation_format") == COOP_BOTH:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_barter,
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(_STATE_BARTER)
        return

    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_how_many,
        keyboard=flow_inline_keyboard(
            rows=bloggers_needed_keyboard(allowed_blogger_counts)
        ),
    )
    await state_store.set_state(_STATE_BLOGGERS)


@router.message_in_state(_STATE_BARTER)
async def handle_barter_description(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle barter description and ask bloggers needed."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    allowed_blogger_counts = deps.get(
        "allowed_blogger_counts", frozenset({1, 3, 5})
    )
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    barter_description = (incoming.text or "").strip()
    coop = (await state_store.get_data()).get("cooperation_format")
    required = coop == COOP_BOTH
    err = validate_barter_description(
        barter_description, required=required, texts=validator_texts
    )
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(barter_description=barter_description or None)
    msg_how_many = await bot_texts_service.get("msg_how_many_creators", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_how_many,
        keyboard=flow_inline_keyboard(
            rows=bloggers_needed_keyboard(allowed_blogger_counts)
        ),
    )
    await state_store.set_state(_STATE_BLOGGERS)


@router.callback_in_state(
    _STATE_BLOGGERS,
    lambda c: bool(
        c.data and c.data.startswith(CALLBACK_ORDER_BLOGGERS_PREFIX)
    ),
)
async def handle_bloggers_needed_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Store bloggers needed from inline and ask product link."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    allowed_blogger_counts = deps.get(
        "allowed_blogger_counts", frozenset({1, 3, 5})
    )
    bloggers_needed = _parse_bloggers_callback_data(incoming.data or "")
    if bloggers_needed is None or bloggers_needed not in allowed_blogger_counts:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await state_store.update_data(bloggers_needed=bloggers_needed)

    msg_product = await bot_texts_service.get("msg_product_link", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_product,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(_STATE_PRODUCT_LINK)


@router.message_in_state(_STATE_BLOGGERS)
async def handle_bloggers_needed_text(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle bloggers count from text and ask product link."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    allowed_blogger_counts = deps.get(
        "allowed_blogger_counts", frozenset({1, 3, 5})
    )
    raw = (incoming.text or "").strip()
    valid_strs = {str(c) for c in allowed_blogger_counts}
    if raw not in valid_strs:
        counts_str = ", ".join(str(c) for c in sorted(allowed_blogger_counts))
        msg_choose = await bot_texts_service.get("msg_choose_count", locale)
        text = msg_choose.format(counts=counts_str)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=text,
            keyboard=flow_inline_keyboard(
                rows=bloggers_needed_keyboard(allowed_blogger_counts)
            ),
        )
        return

    bloggers_needed = int(raw)
    await state_store.update_data(bloggers_needed=bloggers_needed)
    msg_product = await bot_texts_service.get("msg_product_link", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_product,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(_STATE_PRODUCT_LINK)


@router.message_in_state(_STATE_PRODUCT_LINK)
async def handle_product_link(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Store product link and ask content usage. No photo step on Max."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    product_link = (incoming.text or "").strip()
    err = validate_product_link(product_link, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(
        product_link=normalize_url(product_link),
        product_photo_file_id=None,  # No photo upload on Max
    )
    content_texts = await bot_texts_service.get_many(
        ["content_social", "content_ads", "content_both"], locale
    )
    msg_where = await bot_texts_service.get("msg_where_use_ugc", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_where,
        keyboard=flow_inline_keyboard(
            rows=content_usage_keyboard(content_texts)
        ),
    )
    await state_store.set_state(_STATE_CONTENT_USAGE)


@router.callback_in_state(
    _STATE_CONTENT_USAGE,
    lambda c: (
        c.data
        in (
            CALLBACK_ORDER_CONTENT_SOCIAL,
            CALLBACK_ORDER_CONTENT_ADS,
            CALLBACK_ORDER_CONTENT_BOTH,
        )
    ),
)
async def handle_content_usage_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Store content usage from inline and ask deadlines."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    content_usage_offer = _content_usage_from_callback(incoming.data or "")
    if content_usage_offer is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await state_store.update_data(content_usage=content_usage_offer)

    deadlines_texts = await bot_texts_service.get_many(
        ["deadlines_3", "deadlines_7", "deadlines_14"], locale
    )
    msg_deadline = await bot_texts_service.get("msg_order_deadline", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_deadline,
        keyboard=flow_inline_keyboard(rows=deadlines_keyboard(deadlines_texts)),
    )
    await state_store.set_state(_STATE_DEADLINES)


@router.message_in_state(_STATE_CONTENT_USAGE)
async def handle_content_usage_text(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Store content usage from text and ask deadlines."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    text = (incoming.text or "").strip()
    if text not in (
        CONTENT_USAGE_SOCIAL,
        CONTENT_USAGE_ADS,
        CONTENT_USAGE_BOTH,
    ):
        content_texts = await bot_texts_service.get_many(
            ["content_social", "content_ads", "content_both"], locale
        )
        msg_choose = await bot_texts_service.get(
            "msg_choose_from_keyboard", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_choose,
            keyboard=flow_inline_keyboard(
                rows=content_usage_keyboard(content_texts)
            ),
        )
        return

    content_usage_offer = CONTENT_USAGE_TO_OFFER.get(text, text)
    await state_store.update_data(content_usage=content_usage_offer)

    deadlines_texts = await bot_texts_service.get_many(
        ["deadlines_3", "deadlines_7", "deadlines_14"], locale
    )
    msg_deadline = await bot_texts_service.get("msg_order_deadline", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_deadline,
        keyboard=flow_inline_keyboard(rows=deadlines_keyboard(deadlines_texts)),
    )
    await state_store.set_state(_STATE_DEADLINES)


@router.callback_in_state(
    _STATE_DEADLINES,
    lambda c: bool(
        c.data and c.data.startswith(CALLBACK_ORDER_DEADLINES_PREFIX)
    ),
)
async def handle_deadlines_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Store deadlines from inline and ask geography."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    deadlines_offer = _deadlines_offer_from_callback(incoming.data or "")
    if deadlines_offer is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await state_store.update_data(deadlines=deadlines_offer)

    msg_geo = await bot_texts_service.get("msg_order_geo", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_geo,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(_STATE_GEOGRAPHY)


@router.message_in_state(_STATE_DEADLINES)
async def handle_deadlines_text(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Store deadlines from text and ask geography."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    text = (incoming.text or "").strip()
    if text not in (DEADLINES_3, DEADLINES_7, DEADLINES_14):
        deadlines_texts = await bot_texts_service.get_many(
            ["deadlines_3", "deadlines_7", "deadlines_14"], locale
        )
        msg_choose = await bot_texts_service.get(
            "msg_choose_from_keyboard", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_choose,
            keyboard=flow_inline_keyboard(
                rows=deadlines_keyboard(deadlines_texts)
            ),
        )
        return

    deadlines_offer = DEADLINES_TO_OFFER.get(text, text)
    await state_store.update_data(deadlines=deadlines_offer)

    msg_geo = await bot_texts_service.get("msg_order_geo", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_geo,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(_STATE_GEOGRAPHY)


@router.message_in_state(_STATE_GEOGRAPHY)
async def handle_geography(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle geography text, create order, notify admins, send confirmation."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    order_service = deps["order_service"]
    user_role_service = deps["user_role_service"]
    profile_service = deps["profile_service"]
    content_moderation_service = deps["content_moderation_service"]
    config = deps["config"]
    locale = deps.get("locale", "ru")
    country_repo = deps.get("country_repo")

    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    geography = (incoming.text or "").strip()
    err = validate_geography(geography, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        msg_expired = await bot_texts_service.get(
            "msg_session_expired_orders", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        await state_store.clear()
        return

    order_type_val = data.get("order_type", OrderType.UGC_ONLY.value)
    try:
        order_type = OrderType(order_type_val)
    except ValueError:
        order_type = OrderType.UGC_ONLY

    offer_text = data["offer_text"]
    cooperation_format = data.get("cooperation_format", COOP_PAYMENT)
    price = data.get("price", 0.0)
    barter_description = data.get("barter_description")
    bloggers_needed = data["bloggers_needed"]
    product_link = data["product_link"]
    content_usage = data.get("content_usage")
    deadlines = data.get("deadlines")

    if cooperation_format == COOP_BARTER:
        price = 0.0

    order = await order_service.create_order(
        advertiser_id=user_id,
        order_type=order_type,
        product_link=product_link,
        offer_text=offer_text,
        barter_description=barter_description,
        price=price,
        bloggers_needed=bloggers_needed,
        content_usage=content_usage,
        deadlines=deadlines,
        geography=geography,
        product_photo_file_id=None,  # No photo upload on Max
    )

    telegram_messenger = deps.get("telegram_messenger_client")
    if telegram_messenger is not None:
        try:
            await notify_admins_about_order_created(
                order=order,
                messenger_client=telegram_messenger,
                user_role_service=user_role_service,
                content_moderation=content_moderation_service,
                admin_base_url=config.admin.admin_base_url,
                currency_symbol=config.market.currency_symbol,
                country_repo=country_repo,
                advertiser_profile=await profile_service.get_advertiser_profile(
                    user_id
                ),
            )

            support_chat_id = config.referral.referral_support_chat_id
            if support_chat_id.strip():
                advertiser_user = await user_role_service.get_user_by_id(
                    user_id
                )
                advertiser_profile = (
                    await profile_service.get_advertiser_profile(user_id)
                )
                if advertiser_user:
                    await notify_support_chat_about_new_order(
                        order=order,
                        advertiser_user=advertiser_user,
                        advertiser_profile=advertiser_profile,
                        messenger_client=telegram_messenger,
                        support_chat_id=support_chat_id,
                        admin_base_url=config.admin.admin_base_url,
                        currency_symbol=config.market.currency_symbol,
                        country_repo=country_repo,
                    )
        except Exception:
            logger.exception(
                "Failed to send admin notifications for order %s",
                order.order_id,
            )
    else:
        logger.error(
            "telegram_messenger_client not in deps; "
            "skipping admin notifications for order %s",
            order.order_id,
        )

    await state_store.clear()

    msg_order_created = await bot_texts_service.get("msg_order_created", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_order_created or ORDER_CREATED_MESSAGE,
    )
