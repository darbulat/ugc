"""Max handlers for offer responses."""

import contextlib
import logging
from decimal import Decimal, InvalidOperation
from uuid import UUID

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.telegram.handlers.offer_responses import (
    _REJECTION_REASON_BUTTONS,
    _SEND_CONTACT_TEXTS_KEYS,
    OFFER_RESPONSE_TEXTS_KEYS,
    _notify_manager_low_price,
    _send_contact_immediately,
    _send_order_closed_and_remove_keyboard,
)
from ugc_bot.domain.enums import MessengerType, RejectionReason, UserStatus

router = MaxRouter()
logger = logging.getLogger(__name__)

STATE_WAITING_DESIRED_PRICE = "offer_desired_price"


@router.callback(lambda cb: bool(cb.data and cb.data.startswith("offer_skip:")))
async def handle_offer_skip(incoming: IncomingCallback, deps: dict) -> None:
    """Handle blogger pressing skip on offer — show rejection reason menu."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    bot_texts_service = deps["bot_texts_service"]
    locale: str = deps.get("locale", "ru")

    msg_skip = await bot_texts_service.get("msg_offer_skipped", locale)

    raw = (incoming.data or "").split("offer_skip:", 1)[-1]
    try:
        order_id: UUID | None = UUID(raw)
    except (ValueError, IndexError):
        order_id = None

    await messenger_client.answer_callback(
        callback_id=incoming.callback_id, text=""
    )
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id, text=msg_skip
        )
        return

    if order_id is None:
        return

    order_id_hex = str(order_id)
    reason_texts = await bot_texts_service.get_many(
        list(_REJECTION_REASON_BUTTONS.values()), locale
    )
    rows: list[list[Button]] = []
    for reason, text_key in _REJECTION_REASON_BUTTONS.items():
        btn_text = reason_texts.get(text_key, reason.value)
        rows.append(
            [
                Button(
                    text=btn_text,
                    callback_data=f"orr:{order_id_hex}:{reason.value}",
                )
            ]
        )
    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=rows)
    prompt = await bot_texts_service.get("msg_offer_skip_reason_prompt", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=prompt,
        keyboard=keyboard,
    )


@router.callback(lambda cb: bool(cb.data and cb.data.startswith("orr_cancel:")))
async def handle_cancel_price_entry(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Handle cancel button during price entry FSM state."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    offer_dispatch_service: OfferDispatchService = deps[
        "offer_dispatch_service"
    ]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    await state_store.clear()

    raw = (incoming.data or "").split("orr_cancel:", 1)[-1]
    try:
        order_id: UUID | None = UUID(raw)
    except (ValueError, IndexError):
        order_id = None

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is not None and order_id is not None:
        await offer_dispatch_service.record_skip(order_id, user.user_id)

    msg_cancelled = await bot_texts_service.get(
        "msg_price_entry_cancelled", locale
    )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id, text=msg_cancelled
    )
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )


@router.callback(
    lambda cb: bool(
        cb.data
        and cb.data.startswith("orr:")
        and not cb.data.startswith("orr_cancel:")
    )
)
async def handle_rejection_reason(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Handle rejection reason selection callback (orr:{order_hex}:{reason})."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    offer_dispatch_service: OfferDispatchService = deps[
        "offer_dispatch_service"
    ]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    parts = (incoming.data or "").split(":", 2)
    if len(parts) < 3:
        return
    _, order_hex, reason_value = parts
    try:
        order_id = UUID(order_hex)
    except ValueError:
        return
    try:
        reason = RejectionReason(reason_value)
    except ValueError:
        return

    await messenger_client.answer_callback(
        callback_id=incoming.callback_id, text=""
    )
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        return

    if reason == RejectionReason.LOW_PRICE:
        await state_store.set_state(STATE_WAITING_DESIRED_PRICE)
        await state_store.update_data(
            order_id=str(order_id), reason=reason.value
        )
        prompt = await bot_texts_service.get("msg_enter_desired_price", locale)
        cancel_text = await bot_texts_service.get(
            "btn_cancel_price_entry", locale
        )
        cancel_kb = Keyboard(
            kind=KeyboardKind.INLINE,
            rows=[
                [
                    Button(
                        text=cancel_text,
                        callback_data=f"orr_cancel:{order_hex}",
                    )
                ]
            ],
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=prompt,
            keyboard=cancel_kb,
        )
    else:
        await offer_dispatch_service.record_skip(
            order_id, user.user_id, rejection_reason=reason
        )
        reason_texts = await bot_texts_service.get_many(
            list(_REJECTION_REASON_BUTTONS.values()), locale
        )
        reason_label = reason_texts.get(
            _REJECTION_REASON_BUTTONS.get(reason, ""), reason.value
        )
        msg_tpl = await bot_texts_service.get(
            "msg_offer_skipped_with_reason", locale
        )
        msg = msg_tpl.format(reason=reason_label)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg,
        )


@router.message_in_state(STATE_WAITING_DESIRED_PRICE)
async def handle_desired_price(incoming: IncomingMessage, deps: dict) -> None:
    """Handle price entry during waiting_desired_price FSM state."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    offer_dispatch_service: OfferDispatchService = deps[
        "offer_dispatch_service"
    ]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    config = deps["config"]
    locale: str = deps.get("locale", "ru")

    data = await state_store.get_data()
    order_id_str = data.get("order_id")
    if not order_id_str:
        await state_store.clear()
        return
    order_id = UUID(order_id_str)

    if not incoming.text:
        prompt = await bot_texts_service.get("msg_enter_desired_price", locale)
        await messenger_client.send_text(chat_id=incoming.chat_id, text=prompt)
        return

    bounds = await offer_dispatch_service.get_order_price_bounds(order_id)
    if bounds is None:
        await state_store.clear()
        msg_skip = await bot_texts_service.get("msg_offer_skipped", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id, text=msg_skip
        )
        return
    offer_price, max_price = bounds
    currency = config.market.currency_symbol

    try:
        value = Decimal(incoming.text.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        msg_tpl = await bot_texts_service.get("msg_invalid_price", locale)
        msg = msg_tpl.format(min=offer_price, max=max_price, currency=currency)
        await messenger_client.send_text(chat_id=incoming.chat_id, text=msg)
        return

    if value <= offer_price or value > max_price:
        msg_tpl = await bot_texts_service.get("msg_invalid_price", locale)
        msg = msg_tpl.format(min=offer_price, max=max_price, currency=currency)
        await messenger_client.send_text(chat_id=incoming.chat_id, text=msg)
        return

    external_id = incoming.user.external_id
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await state_store.clear()
        return

    result = await offer_dispatch_service.record_skip(
        order_id,
        user.user_id,
        rejection_reason=RejectionReason.LOW_PRICE,
        desired_price=value,
    )
    await state_store.clear()

    msg_tpl = await bot_texts_service.get("msg_offer_skipped_low_price", locale)
    msg = msg_tpl.format(price=value, currency=currency)
    await messenger_client.send_text(chat_id=incoming.chat_id, text=msg)

    if result.manager_id:
        await _notify_manager_low_price(
            result=result,
            user=user,
            external_id=external_id,
            offer_price=offer_price,
            desired_price=value,
            currency=currency,
            order_id=order_id,
            user_role_service=user_role_service,
            bot_texts_service=bot_texts_service,
            messenger_client=messenger_client,
        )


async def _check_offer_response_eligibility(
    incoming: IncomingCallback,
    deps: dict,
    locale: str,
) -> bool:
    """Check if the user is eligible to respond to an offer.

    Returns True if eligible, False if a denial reply was already sent.
    """
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    profile_service: ProfileService = deps["profile_service"]
    offer_response_rate_limiter = deps.get("offer_response_rate_limiter")
    bot_texts_service = deps["bot_texts_service"]

    offer_msgs = await bot_texts_service.get_many(
        list(OFFER_RESPONSE_TEXTS_KEYS), locale
    )

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=offer_msgs.get("msg_profile_not_found_role", ""),
        )
        return False
    if user.status == UserStatus.BLOCKED:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=offer_msgs.get("msg_offer_response_blocked", ""),
        )
        return False
    if user.status == UserStatus.PAUSE:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=offer_msgs.get("msg_offer_response_pause", ""),
        )
        return False

    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        msg_profile_fill = await bot_texts_service.get(
            "msg_creator_profile_fill", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_profile_fill,
        )
        return False
    if not blogger_profile.confirmed:
        msg_instagram_first = await bot_texts_service.get(
            "msg_confirm_instagram_first", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_instagram_first,
        )
        return False

    limiter = offer_response_rate_limiter
    rate_limit_hit = limiter is not None and not await limiter.allow_async(
        str(user.user_id)
    )
    if rate_limit_hit:
        msg_too_many = await bot_texts_service.get(
            "msg_too_many_requests", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_too_many,
        )
        return False

    return True


@router.callback(lambda cb: bool(cb.data and cb.data.startswith("offer:")))
async def handle_offer_response(incoming: IncomingCallback, deps: dict) -> None:
    """Handle blogger response to offer."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    profile_service: ProfileService = deps["profile_service"]
    offer_response_service: OfferResponseService = deps[
        "offer_response_service"
    ]
    interaction_service = deps["interaction_service"]
    bot_texts_service = deps["bot_texts_service"]
    config = deps["config"]
    locale: str = deps.get("locale", "ru")

    if not await _check_offer_response_eligibility(incoming, deps, locale):
        return

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        return

    raw = (incoming.data or "").split("offer:", 1)[-1]
    try:
        order_id = UUID(raw)
    except ValueError:
        msg = await bot_texts_service.get("err_order_invalid_id", locale)
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg,
        )
        return

    try:
        result = await offer_response_service.respond_and_finalize(
            order_id, user.user_id
        )
    except OrderCreationError:
        await _send_order_closed_and_remove_keyboard(
            incoming, messenger_client, bot_texts_service, locale
        )
        return

    if result.accepted:
        text = await bot_texts_service.get("msg_offer_accepted", locale)
    else:
        text = await bot_texts_service.get(
            "msg_offer_order_filled_toast", locale
        )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text=text,
    )
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )

    if not result.accepted:
        msg_waitlist = await bot_texts_service.get(
            "msg_offer_order_filled", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_waitlist,
        )
        return

    if result.order.product_link:
        await messenger_client.send_text(
            chat_id=incoming.chat_id, text=result.order.product_link
        )
    msg_what_next = await bot_texts_service.get(
        "msg_blogger_after_response_what_next", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id, text=msg_what_next
    )

    contact_texts = await bot_texts_service.get_many(
        list(_SEND_CONTACT_TEXTS_KEYS), locale
    )

    manager = None
    if result.manager_id:
        manager = await user_role_service.get_user_by_id(result.manager_id)

    await _send_contact_immediately(
        order=result.order,
        blogger_id=user.user_id,
        blogger_chat_id=incoming.chat_id,
        response_count=result.response_count,
        user_role_service=user_role_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
        texts=contact_texts,
        bot_texts_service=bot_texts_service,
        manager=manager,
        currency_symbol=config.market.currency_symbol,
    )
