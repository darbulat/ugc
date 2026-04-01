"""Handlers for offer responses."""

import contextlib
import logging
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
    SkipResult,
)
from ugc_bot.application.services.offer_response_service import (
    OfferResponseResult,
    OfferResponseService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.utils import (
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
    send_with_retry,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import MessengerType, OrderType, RejectionReason

router = Router()

OFFER_RESPONSE_TEXTS_KEYS = (
    "msg_profile_not_found_role",
    "msg_offer_response_blocked",
    "msg_offer_response_pause",
)
_SEND_CONTACT_TEXTS_KEYS = (
    "lbl_creator_fallback",
    "msg_offer_new_response",
    "msg_advertiser_new_response_what_next",
    "msg_advertiser_contacts_warning",
    "msg_offer_contacts_header",
    "lbl_phone_dash",
    "lbl_telegram_dash",
    "msg_order_type_ugc",
    "msg_order_type_placement",
    "btn_open_profile",
    "btn_write_telegram",
    "btn_write_max",
)
logger = logging.getLogger(__name__)
_send_retries = 3
_send_retry_delay_seconds = 0.5


class OfferSkipStates(StatesGroup):
    waiting_desired_price = State()


_REJECTION_REASON_BUTTONS = {
    RejectionReason.LOW_PRICE: "btn_reject_low_price",
    RejectionReason.WRONG_FORMAT: "btn_reject_wrong_format",
    RejectionReason.UNINTERESTING_PRODUCT: "btn_reject_uninteresting",
    RejectionReason.NO_TIME: "btn_reject_no_time",
    RejectionReason.ALREADY_WORKING_WITH_BRAND: "btn_reject_already_working",
}


async def _send_order_closed_and_remove_keyboard(
    incoming: IncomingCallback,
    messenger_client: MessengerClient,
    bot_texts_service: BotTextsService,
    locale: str,
) -> None:
    """Answer callback, remove offer keyboard, and send order-closed message."""
    msg_closed = await bot_texts_service.get("msg_order_closed", locale)
    msg_closed_full = await bot_texts_service.get(
        "msg_order_closed_full", locale
    )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text=msg_closed,
    )
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_closed_full,
    )


async def _reply_offer_response_result(
    incoming: IncomingCallback,
    result: OfferResponseResult,
    blogger_id: UUID,
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    interaction_service: InteractionService,
    bot_texts_service: BotTextsService,
    locale: str,
    currency_symbol: str = "₽",
) -> None:
    """Answer callback, remove keyboard; if accepted, send link and contact."""
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
    if result.accepted:
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
        manager: User | None = None
        if result.manager_id:
            manager = await user_role_service.get_user_by_id(result.manager_id)
        await _send_contact_immediately(
            order=result.order,
            blogger_id=blogger_id,
            blogger_chat_id=incoming.chat_id,
            response_count=result.response_count,
            user_role_service=user_role_service,
            profile_service=profile_service,
            interaction_service=interaction_service,
            messenger_client=messenger_client,
            texts=contact_texts,
            bot_texts_service=bot_texts_service,
            manager=manager,
            currency_symbol=currency_symbol,
        )


def _parse_offer_skip_order_id(callback_data: str) -> UUID | None:
    """Parse order_id from 'offer_skip:{order_id}'."""
    if not callback_data or not callback_data.startswith("offer_skip:"):
        return None
    try:
        return UUID(callback_data.split(":", 1)[1])
    except (ValueError, IndexError):
        return None


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("offer_skip:")
)
async def handle_offer_skip(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    offer_dispatch_service: OfferDispatchService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle blogger pressing 'Пропустить' on offer.

    Shows rejection reason selection menu instead of recording skip immediately.
    """
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale
    msg_skip = await bot_texts_service.get("msg_offer_skipped", locale)
    order_id = _parse_offer_skip_order_id(callback.data or "")

    # Answer callback (empty toast) and remove original offer keyboard
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

    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=msg_skip,
        blocked_msg=msg_skip,
        pause_msg=msg_skip,
    )
    if user is not None:
        user = await user_role_service.update_telegram(
            user, callback.from_user.username
        )
    if order_id is None or user is None:
        return

    # Build reason selection keyboard
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


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("orr_cancel:")
)
async def handle_cancel_price_entry(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    offer_dispatch_service: OfferDispatchService,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle cancel button during price entry FSM state."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale

    await state.clear()

    raw = (callback.data or "").split("orr_cancel:", 1)[-1]
    try:
        order_id = UUID(raw)
    except (ValueError, IndexError):
        order_id = None

    msg_skip = await bot_texts_service.get("msg_offer_skipped", locale)
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=msg_skip,
        blocked_msg=msg_skip,
        pause_msg=msg_skip,
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


@router.callback_query(
    lambda callback: (
        callback.data
        and callback.data.startswith("orr:")
        and not callback.data.startswith("orr_cancel:")
    )
)
async def handle_rejection_reason(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    offer_dispatch_service: OfferDispatchService,
    bot_texts_service: BotTextsService,
    config: AppConfig,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle rejection reason selection callback (orr:{order_hex}:{reason})."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale

    # Parse callback data: orr:{order_hex}:{reason}
    parts = (callback.data or "").split(":", 2)
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

    msg_skip = await bot_texts_service.get("msg_offer_skipped", locale)
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=msg_skip,
        blocked_msg=msg_skip,
        pause_msg=msg_skip,
    )
    if user is None:
        return

    if reason == RejectionReason.LOW_PRICE:
        # Enter FSM for price entry
        await state.set_state(OfferSkipStates.waiting_desired_price)
        await state.update_data(order_id=str(order_id), reason=reason.value)
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
        # Non-price reason: record skip immediately
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


async def _notify_manager_low_price(
    result: SkipResult,
    user: User,
    external_id: str,
    offer_price: Decimal,
    desired_price: Decimal,
    currency: str,
    order_id: UUID,
    user_role_service: UserRoleService,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient,
) -> None:
    """Notify manager about low-price rejection."""
    assert result.manager_id is not None
    manager = await user_role_service.get_user_by_id(result.manager_id)
    if manager and manager.telegram_id:
        mgr_locale = manager.language or "ru"
        mgr_msg_tpl = await bot_texts_service.get(
            "msg_manager_low_price_notification", mgr_locale
        )
        blogger_handle = user.telegram or user.username or external_id
        if blogger_handle and not blogger_handle.startswith("@"):
            blogger_handle = f"@{blogger_handle}"
        mgr_msg = mgr_msg_tpl.format(
            blogger=blogger_handle,
            desired_price=desired_price,
            offer_price=result.order_price or offer_price,
            currency=currency,
            product_link=result.product_link or "",
        )
        await send_with_retry(
            messenger_client,
            chat_id=manager.telegram_id,
            text=mgr_msg,
            retries=_send_retries,
            delay_seconds=_send_retry_delay_seconds,
            logger=logger,
            extra={"order_id": str(order_id)},
        )


@router.message(OfferSkipStates.waiting_desired_price)
async def handle_desired_price(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    offer_dispatch_service: OfferDispatchService,
    bot_texts_service: BotTextsService,
    config: AppConfig,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle price entry during FSM waiting_desired_price state."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    locale = user_locale
    data = await state.get_data()
    order_id_str = data.get("order_id")
    if not order_id_str:
        await state.clear()
        return
    order_id = UUID(order_id_str)

    if not message.text:
        prompt = await bot_texts_service.get("msg_enter_desired_price", locale)
        await messenger_client.send_text(
            chat_id=str(message.chat.id),
            text=prompt,
        )
        return

    # Get order price bounds via service
    bounds = await offer_dispatch_service.get_order_price_bounds(order_id)
    if bounds is None:
        await state.clear()
        msg_skip = await bot_texts_service.get("msg_offer_skipped", locale)
        await messenger_client.send_text(
            chat_id=str(message.chat.id), text=msg_skip
        )
        return
    offer_price, max_price = bounds
    currency = config.market.currency_symbol

    try:
        value = Decimal(message.text.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        msg_tpl = await bot_texts_service.get("msg_invalid_price", locale)
        msg = msg_tpl.format(min=offer_price, max=max_price, currency=currency)
        await messenger_client.send_text(
            chat_id=str(message.chat.id),
            text=msg,
        )
        return

    if value <= offer_price or value > max_price:
        msg_tpl = await bot_texts_service.get("msg_invalid_price", locale)
        msg = msg_tpl.format(min=offer_price, max=max_price, currency=currency)
        await messenger_client.send_text(
            chat_id=str(message.chat.id),
            text=msg,
        )
        return

    # Resolve user
    from_user = message.from_user
    if not from_user:
        await state.clear()
        return
    external_id = str(from_user.id)
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await state.clear()
        return

    result = await offer_dispatch_service.record_skip(
        order_id,
        user.user_id,
        rejection_reason=RejectionReason.LOW_PRICE,
        desired_price=value,
    )
    await state.clear()

    msg_tpl = await bot_texts_service.get("msg_offer_skipped_low_price", locale)
    msg = msg_tpl.format(price=value, currency=currency)
    await messenger_client.send_text(
        chat_id=str(message.chat.id),
        text=msg,
    )

    # Notify manager if available
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


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("offer:")
)
async def handle_offer_response(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    order_repo: OrderRepository,
    offer_response_rate_limiter: Any,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Show confirmation message with brief link before accepting offer."""

    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale
    offer_msgs = await bot_texts_service.get_many(
        list(OFFER_RESPONSE_TEXTS_KEYS), locale
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=offer_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=offer_msgs.get("msg_offer_response_blocked", ""),
        pause_msg=offer_msgs.get("msg_offer_response_pause", ""),
    )
    if user is None:
        return
    user = await user_role_service.update_telegram(
        user, callback.from_user.username
    )
    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        msg_profile_fill = await bot_texts_service.get(
            "msg_creator_profile_fill", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_profile_fill,
        )
        return
    if not blogger_profile.confirmed:
        msg_instagram_first = await bot_texts_service.get(
            "msg_confirm_instagram_first", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_instagram_first,
        )
        return

    if not await offer_response_rate_limiter.allow_async(str(user.user_id)):
        msg_too_many = await bot_texts_service.get(
            "msg_too_many_requests", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_too_many,
        )
        return

    raw = incoming.data.split("offer:", 1)[-1] if incoming.data else ""
    try:
        order_id = UUID(raw)
    except ValueError:
        msg = await bot_texts_service.get("err_order_invalid_id", locale)
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg,
        )
        return

    order = await order_repo.get_by_id(order_id)
    if order is None:
        await _send_order_closed_and_remove_keyboard(
            incoming, messenger_client, bot_texts_service, locale
        )
        return

    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text="",
    )
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )

    if order.brief_link:
        brief_label = await bot_texts_service.get(
            "msg_offer_brief_link", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=f"{brief_label}\n{order.brief_link}",
        )

    confirm_text = await bot_texts_service.get(
        "msg_offer_confirm_response", locale
    )
    btn_texts = await bot_texts_service.get_many(
        ["btn_offer_confirm", "btn_offer_cancel"], locale
    )
    keyboard = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=btn_texts.get("btn_offer_confirm", "Готов"),
                    callback_data=f"offer_confirm:{order_id}",
                )
            ],
            [
                Button(
                    text=btn_texts.get("btn_offer_cancel", "Отмена"),
                    callback_data=f"offer_cancel:{order_id}",
                )
            ],
        ],
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=confirm_text,
        keyboard=keyboard,
    )


@router.callback_query(
    lambda cb: cb.data and cb.data.startswith("offer_confirm:")
)
async def handle_offer_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    offer_response_service: OfferResponseService,
    interaction_service: InteractionService,
    offer_response_rate_limiter: Any,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Confirm offer response after creator reviewed the brief."""

    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale
    offer_msgs = await bot_texts_service.get_many(
        list(OFFER_RESPONSE_TEXTS_KEYS), locale
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=offer_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=offer_msgs.get("msg_offer_response_blocked", ""),
        pause_msg=offer_msgs.get("msg_offer_response_pause", ""),
    )
    if user is None:
        return

    raw = incoming.data.split("offer_confirm:", 1)[-1] if incoming.data else ""
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

    await _reply_offer_response_result(
        incoming,
        result,
        user.user_id,
        messenger_client,
        user_role_service,
        profile_service,
        interaction_service,
        bot_texts_service,
        locale,
        currency_symbol=config.market.currency_symbol,
    )


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("offer_cancel:")
)
async def handle_offer_cancel(
    callback: CallbackQuery,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Cancel offer response — remove confirmation keyboard."""

    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale

    msg_cancelled = await bot_texts_service.get(
        "msg_offer_confirm_cancelled", locale
    )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text=msg_cancelled,
    )
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )


def _format_ugc_type(order: Order, texts: dict[str, str] | None = None) -> str:
    """Return human-readable order/format type for advertiser message."""
    t = texts or {}
    if order.order_type == OrderType.UGC_PLUS_PLACEMENT:
        return t.get("msg_order_type_placement", "UGC + размещение")
    return t.get("msg_order_type_ugc", "UGC-видео для бренда")


def _build_advertiser_contact_content(
    order: Order,
    creator_name: str,
    city: str,
    ugc_format: str,
    profile_url: str,
    has_telegram: bool,
    telegram_handle: str,
    texts: dict[str, str],
    creator_external_id: str | None = None,
    creator_max_id: str | None = None,
    blogger_phone: str | None = None,
) -> tuple[str, Keyboard | None]:
    """Build contact message and inline keyboard for advertiser."""
    t = texts
    msg_new = t.get(
        "msg_offer_new_response",
        "Новый отклик по вашему заказу 🙌\n\n"
        "👤 Креатор: {creator}\n"
        "📍 Город: {city}\n"
        "🎬 Формат: {format}\n"
        "💼 Готов работать на условиях оффера\n"
        "🔗 Профиль креатора:\n{profile_url}",
    )
    what_next = t.get("msg_advertiser_new_response_what_next", "")
    contact_text = msg_new.format(
        creator=creator_name,
        city=city,
        format=ugc_format,
        profile_url=profile_url,
    ) + ("\n\n" + what_next if what_next else "")

    if blogger_phone:
        lbl = t.get("lbl_phone", "Телефон")
        contact_text += f"\n📞 {lbl}: {blogger_phone}"

    url = profile_url.strip()
    if url and not url.startswith("http"):
        url = "https://" + url
    buttons: list[Button] = []
    if url.startswith("http"):
        buttons.append(
            Button(
                text=t.get("btn_open_profile", "🔗 Открыть профиль"),
                url=url,
            )
        )
    if has_telegram and telegram_handle:
        buttons.append(
            Button(
                text=t.get("btn_write_telegram", "Написать в телеграм"),
                url=f"https://t.me/{telegram_handle.lstrip('@')}",
            )
        )
    elif creator_external_id and creator_external_id.isdigit():
        buttons.append(
            Button(
                text=t.get("btn_write_telegram", "Написать в телеграм"),
                url=f"tg://user?id={creator_external_id}",
            )
        )
    if creator_max_id:
        buttons.append(
            Button(
                text=t.get("btn_write_max", "Написать в Макс"),
                url=f"max://max.ru/{creator_max_id}",
            )
        )
    keyboard = (
        Keyboard(kind=KeyboardKind.INLINE, rows=[buttons]) if buttons else None
    )
    return contact_text, keyboard


def _build_blogger_contacts_text(
    advertiser_telegram: str | None,
    advertiser_phone: str | None,
    texts: dict[str, str],
    advertiser_external_id: str | None = None,
) -> str:
    """Build message with advertiser contacts for blogger."""
    t = texts
    header = t.get(
        "msg_offer_contacts_header", "📞 Контакты заказчика для связи:\n\n"
    )
    parts = [header]
    if advertiser_telegram and advertiser_telegram.strip():
        tg = advertiser_telegram.strip().lstrip("@")
        parts.append(f"Telegram: @{tg}\n")
    elif advertiser_external_id and advertiser_external_id.isdigit():
        parts.append(f"Telegram: tg://user?id={advertiser_external_id}\n")
    else:
        parts.append(t.get("lbl_telegram_dash", "Telegram: —") + "\n")
    if advertiser_phone:
        parts.append(f"Телефон: {advertiser_phone}")
    else:
        parts.append(t.get("lbl_phone_dash", "Телефон: —"))
    return "".join(parts)


async def _deliver_to_recipient(
    client: MessengerClient,
    chat_id: str,
    text: str,
    keyboard: Keyboard | None,
    order_id: UUID,
    response_count: int,
    warning_text: str,
    parse_mode: str | None = None,
    extra: dict | None = None,
) -> None:
    """Send contact message + optional first-response warning to a recipient."""
    send_extra = extra or {"order_id": str(order_id)}
    await send_with_retry(
        client,
        chat_id=chat_id,
        text=text,
        keyboard=keyboard,
        retries=_send_retries,
        delay_seconds=_send_retry_delay_seconds,
        logger=logger,
        extra=send_extra,
    )
    if response_count == 1 and warning_text:
        await send_with_retry(
            client,
            chat_id=chat_id,
            text=warning_text,
            parse_mode=parse_mode,
            retries=_send_retries,
            delay_seconds=_send_retry_delay_seconds,
            logger=logger,
            extra=send_extra,
        )


async def _send_contact_immediately(
    order: Order,
    blogger_id: UUID,
    blogger_chat_id: str,
    response_count: int,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    interaction_service: InteractionService | None,
    messenger_client: MessengerClient,
    texts: dict[str, str],
    bot_texts_service: BotTextsService,
    manager: User | None = None,
    currency_symbol: str = "₽",
    telegram_messenger_client: MessengerClient | None = None,
) -> None:
    """Send contact to advertiser after each response (TZ format).

    Also sends advertiser's Telegram and phone to the blogger when they get
    into the order.
    """
    user = await user_role_service.get_user_by_id(blogger_id)
    profile = await profile_service.get_blogger_profile(blogger_id)
    if user is None or profile is None:
        logger.warning(
            "Cannot send contact: user or profile not found",
            extra={"order_id": order.order_id, "blogger_id": blogger_id},
        )
        return

    advertiser = await user_role_service.get_user_by_id(order.advertiser_id)

    # Resolve per-recipient texts in their own locale
    adv_locale = (advertiser.language if advertiser else None) or "ru"
    adv_texts = await bot_texts_service.get_many(
        list(_SEND_CONTACT_TEXTS_KEYS), adv_locale
    )

    t_adv = adv_texts
    creator_name = user.username or t_adv.get("lbl_creator_fallback", "Креатор")
    ugc_format = _format_ugc_type(order, t_adv)
    contact_text, open_profile_kb = _build_advertiser_contact_content(
        order,
        creator_name=creator_name,
        city=profile.city or "—",
        ugc_format=ugc_format,
        profile_url=profile.instagram_url,
        has_telegram=bool(user.telegram and user.telegram.strip()),
        telegram_handle=user.telegram or "",
        texts=t_adv,
        creator_external_id=user.telegram_id,
        creator_max_id=user.max_id,
        blogger_phone=profile.phone,
    )

    # Resolve the right client for the advertiser's messenger
    tg_client = telegram_messenger_client or messenger_client
    adv_warning = t_adv.get("msg_advertiser_contacts_warning", "")
    if advertiser and advertiser.telegram_id:
        await _deliver_to_recipient(
            tg_client,
            chat_id=advertiser.telegram_id,
            text=contact_text,
            keyboard=open_profile_kb,
            order_id=order.order_id,
            response_count=response_count,
            warning_text=adv_warning,
            parse_mode="Markdown",
        )
    if advertiser and advertiser.max_chat_id:
        await _deliver_to_recipient(
            messenger_client,
            chat_id=advertiser.max_chat_id,
            text=contact_text,
            keyboard=open_profile_kb,
            order_id=order.order_id,
            response_count=response_count,
            warning_text=adv_warning,
        )

    if manager and manager.telegram_id:
        mgr_locale = manager.language or "ru"
        mgr_texts = await bot_texts_service.get_many(
            list(_SEND_CONTACT_TEXTS_KEYS), mgr_locale
        )
        t_mgr = mgr_texts
        mgr_creator_name = user.username or t_mgr.get(
            "lbl_creator_fallback", "Креатор"
        )
        mgr_ugc_format = _format_ugc_type(order, t_mgr)
        mgr_contact_text, mgr_kb = _build_advertiser_contact_content(
            order,
            creator_name=mgr_creator_name,
            city=profile.city or "—",
            ugc_format=mgr_ugc_format,
            profile_url=profile.instagram_url,
            has_telegram=bool(user.telegram and user.telegram.strip()),
            telegram_handle=user.telegram or "",
            texts=t_mgr,
            creator_external_id=user.telegram_id,
            creator_max_id=user.max_id,
            blogger_phone=profile.phone,
        )
        mgr_contact_text += f"\n💰 Цена заказа: {order.price} {currency_symbol}"
        await send_with_retry(
            tg_client,
            chat_id=manager.telegram_id,
            text=mgr_contact_text,
            keyboard=mgr_kb,
            retries=_send_retries,
            delay_seconds=_send_retry_delay_seconds,
            logger=logger,
            extra={
                "order_id": str(order.order_id),
                "manager_id": str(manager.user_id),
            },
        )

    if manager:
        blogger_contact_text = _build_blogger_contacts_text(
            advertiser_telegram=manager.telegram,
            advertiser_phone=None,
            texts=texts,
            advertiser_external_id=manager.telegram_id,
        )
    else:
        advertiser_profile = await profile_service.get_advertiser_profile(
            order.advertiser_id
        )
        blogger_contact_text = _build_blogger_contacts_text(
            advertiser_telegram=advertiser.telegram if advertiser else None,
            advertiser_phone=advertiser_profile.phone
            if advertiser_profile
            else None,
            texts=texts,
            advertiser_external_id=advertiser.telegram_id
            if advertiser
            else None,
        )
    await send_with_retry(
        messenger_client,
        chat_id=blogger_chat_id,
        text=blogger_contact_text,
        retries=_send_retries,
        delay_seconds=_send_retry_delay_seconds,
        logger=logger,
        extra={"order_id": str(order.order_id), "blogger_id": str(blogger_id)},
    )

    if interaction_service:
        await interaction_service.reactivate_or_create_for_contacts_sent(
            order_id=order.order_id,
            blogger_id=blogger_id,
            advertiser_id=order.advertiser_id,
        )
