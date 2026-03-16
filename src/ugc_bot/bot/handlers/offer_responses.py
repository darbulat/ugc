"""Handlers for offer responses."""

import contextlib
import logging
from typing import Any
from uuid import UUID

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

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
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.offer_response_service import (
    OfferResponseResult,
    OfferResponseService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
    send_with_retry,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import OrderType

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
)
logger = logging.getLogger(__name__)
_send_retries = 3
_send_retry_delay_seconds = 0.5


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

    Records skip in offer_dispatches (accepted=False, in_offer=False) and
    removes inline keyboard.
    """
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale
    msg_skip = await bot_texts_service.get("msg_offer_skipped", locale)
    order_id = _parse_offer_skip_order_id(callback.data or "")
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=msg_skip,
        blocked_msg=msg_skip,
        pause_msg=msg_skip,
    )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id, text=msg_skip
    )
    if user is not None:
        user = await user_role_service.update_telegram(
            user, callback.from_user.username
        )
    if order_id is not None and user is not None:
        await offer_dispatch_service.record_skip(order_id, user.user_id)
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("offer:")
)
async def handle_offer_response(
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
    """Handle blogger response to offer."""

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

    if not await offer_response_rate_limiter.allow_async(user.external_id):
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
    keyboard = (
        Keyboard(kind=KeyboardKind.INLINE, rows=[buttons]) if buttons else None
    )
    return contact_text, keyboard


def _build_blogger_contacts_text(
    advertiser_telegram: str | None,
    advertiser_phone: str | None,
    texts: dict[str, str],
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
    else:
        parts.append(t.get("lbl_telegram_dash", "Telegram: —") + "\n")
    if advertiser_phone:
        parts.append(f"Телефон: {advertiser_phone}")
    else:
        parts.append(t.get("lbl_phone_dash", "Телефон: —"))
    return "".join(parts)


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
    )

    if advertiser and advertiser.external_id.isdigit():
        await send_with_retry(
            messenger_client,
            chat_id=advertiser.external_id,
            text=contact_text,
            keyboard=open_profile_kb,
            retries=_send_retries,
            delay_seconds=_send_retry_delay_seconds,
            logger=logger,
            extra={"order_id": str(order.order_id)},
        )
        if response_count == 1:
            warning = t_adv.get("msg_advertiser_contacts_warning", "")
            if warning:
                await send_with_retry(
                    messenger_client,
                    chat_id=advertiser.external_id,
                    text=warning,
                    parse_mode="Markdown",
                    retries=_send_retries,
                    delay_seconds=_send_retry_delay_seconds,
                    logger=logger,
                    extra={"order_id": str(order.order_id)},
                )

    if manager and manager.external_id.isdigit():
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
        )
        await send_with_retry(
            messenger_client,
            chat_id=manager.external_id,
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

    advertiser_profile = await profile_service.get_advertiser_profile(
        order.advertiser_id
    )
    blogger_contact_text = _build_blogger_contacts_text(
        advertiser_telegram=advertiser.telegram if advertiser else None,
        advertiser_phone=advertiser_profile.phone
        if advertiser_profile
        else None,
        texts=texts,
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
        await interaction_service.create_for_contacts_sent(
            order_id=order.order_id,
            blogger_id=blogger_id,
            advertiser_id=order.advertiser_id,
        )
