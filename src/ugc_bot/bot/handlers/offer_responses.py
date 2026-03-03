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
from ugc_bot.bot.handlers.keyboards import flow_keyboard
from ugc_bot.bot.handlers.profile import _BLOGGER_AGREEMENTS_STATE
from ugc_bot.bot.handlers.security_warnings import (
    ADVERTISER_CONTACTS_WARNING,
    ADVERTISER_NEW_RESPONSE_WHAT_NEXT,
)
from ugc_bot.bot.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
    send_with_retry,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import Order

router = Router()
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
        text = await bot_texts_service.get("msg_offer_order_filled", locale)
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
        await _send_contact_immediately(
            order=result.order,
            blogger_id=blogger_id,
            blogger_chat_id=incoming.chat_id,
            response_count=result.response_count,
            user_role_service=user_role_service,
            profile_service=profile_service,
            interaction_service=interaction_service,
            messenger_client=messenger_client,
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
    order_id = _parse_offer_skip_order_id(callback.data or "")
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Ок, пропущено.",
        blocked_msg="Ок, пропущено.",
        pause_msg="Ок, пропущено.",
    )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id, text="Ок, пропущено."
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
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle blogger response to offer."""

    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Заблокированные пользователи не могут откликаться.",
        pause_msg="Пользователи на паузе не могут откликаться.",
    )
    if user is None:
        return
    locale = config.market.default_locale
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

    if getattr(user, "agreement_confirmed_at", None) is None:
        msg_confirm_first = await bot_texts_service.get(
            "msg_confirm_agreement_first", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_confirm_first,
        )
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
        )
        confirm_btn = agree_texts.get("btn_confirm_agreement", "")
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=agreements_text,
            keyboard=flow_keyboard(
                keyboard=[[Button(text=confirm_btn)]],
            ),
            parse_mode="HTML",
        )
        await state.update_data(user_id=user.user_id)
        await state.set_state(_BLOGGER_AGREEMENTS_STATE)
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
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Неверный идентификатор заказа.",
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


def _format_ugc_type(order: Order) -> str:
    """Return human-readable order/format type for advertiser message."""
    if order.order_type.value == "ugc_plus_placement":
        return "UGC + размещение"
    return "UGC-видео для бренда"


BLOGGER_ADVERTISER_CONTACTS_HEADER = "📞 Контакты заказчика для связи:\n\n"


async def _send_contact_immediately(
    order: Order,
    blogger_id: UUID,
    blogger_chat_id: str,
    response_count: int,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    interaction_service: InteractionService | None,
    messenger_client: MessengerClient,
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

    creator_name = user.username or "Креатор"
    ugc_format = _format_ugc_type(order)
    contact_text = (
        "Новый отклик по вашему заказу 🙌\n\n"
        f"👤 Креатор: {creator_name}\n"
        f"📍 Город: {profile.city or '—'}\n"
        f"🎬 Формат: {ugc_format}\n"
        "💼 Готов работать на условиях оффера\n"
        f"🔗 Профиль креатора:\n{profile.instagram_url}\n\n"
        + ADVERTISER_NEW_RESPONSE_WHAT_NEXT
    )

    profile_url = profile.instagram_url.strip()
    if profile_url and not profile_url.startswith("http"):
        profile_url = "https://" + profile_url
    buttons: list[Button] = []
    if profile_url.startswith("http"):
        buttons.append(Button(text="🔗 Открыть профиль", url=profile_url))
    if user.telegram and user.telegram.strip():
        buttons.append(
            Button(
                text="Написать в телеграм",
                url=f"https://t.me/{user.telegram.lstrip('@')}",
            )
        )
    open_profile_kb = (
        Keyboard(kind=KeyboardKind.INLINE, rows=[buttons]) if buttons else None
    )

    advertiser = await user_role_service.get_user_by_id(order.advertiser_id)
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
            await send_with_retry(
                messenger_client,
                chat_id=advertiser.external_id,
                text=ADVERTISER_CONTACTS_WARNING,
                parse_mode="Markdown",
                retries=_send_retries,
                delay_seconds=_send_retry_delay_seconds,
                logger=logger,
                extra={"order_id": str(order.order_id)},
            )

    # Send advertiser's Telegram and phone to blogger
    advertiser_profile = await profile_service.get_advertiser_profile(
        order.advertiser_id
    )
    parts = [BLOGGER_ADVERTISER_CONTACTS_HEADER]
    if advertiser and advertiser.telegram and advertiser.telegram.strip():
        tg = advertiser.telegram.strip().lstrip("@")
        parts.append(f"Telegram: @{tg}\n")
    else:
        parts.append("Telegram: —\n")
    if advertiser_profile and advertiser_profile.phone:
        parts.append(f"Телефон: {advertiser_profile.phone}")
    else:
        parts.append("Телефон: —")
    blogger_contact_text = "".join(parts)
    await send_with_retry(
        messenger_client,
        chat_id=blogger_chat_id,
        text=blogger_contact_text,
        retries=_send_retries,
        delay_seconds=_send_retry_delay_seconds,
        logger=logger,
        extra={"order_id": str(order.order_id), "blogger_id": str(blogger_id)},
    )

    # Create interaction for feedback tracking (72 hour timer starts)
    if interaction_service:
        await interaction_service.create_for_contacts_sent(
            order_id=order.order_id,
            blogger_id=blogger_id,
            advertiser_id=order.advertiser_id,
        )
