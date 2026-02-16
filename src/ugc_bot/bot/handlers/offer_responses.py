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
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    flow_keyboard,
)
from ugc_bot.bot.handlers.profile import _BLOGGER_AGREEMENTS_STATE
from ugc_bot.bot.handlers.security_warnings import (
    ADVERTISER_CONTACTS_WARNING,
    ADVERTISER_NEW_RESPONSE_WHAT_NEXT,
    BLOGGER_AFTER_RESPONSE_WHAT_NEXT,
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

ORDER_CLOSED_MESSAGE = (
    "❗ Заказ уже закрыт\n\n"
    "Спасибо за отклик — все креаторы по этому заказу уже подобраны.\n\n"
    "Мы обязательно пришлём новые заказы, как только они появятся.\n\n"
    "Следите за уведомлениями в боте 🙌"
)


async def _send_order_closed_and_remove_keyboard(
    incoming: IncomingCallback,
    messenger_client: MessengerClient,
) -> None:
    """Answer callback, remove offer keyboard, and send order-closed message."""
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text="Заказ уже закрыт.",
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
        text=ORDER_CLOSED_MESSAGE,
    )


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("offer_skip:")
)
async def handle_offer_skip(
    callback: CallbackQuery,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle blogger pressing 'Пропустить' on offer (no response recorded).

    Removes inline keyboard so 'Готов снять UGC' can no longer be pressed.
    """
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id, text="Ок, пропущено."
    )
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
    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Профиль блогера не заполнен. Команда: /creator",
        )
        return
    if not blogger_profile.confirmed:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Подтвердите Instagram перед откликом.",
        )
        return

    if getattr(user, "agreement_confirmed_at", None) is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Сначала подтвердите согласие.",
        )
        agreements_text = format_agreements_message(
            config,
            intro="Пожалуйста, подтвердите согласие с документами платформы.",
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=agreements_text,
            keyboard=flow_keyboard(
                keyboard=[[Button(text=CONFIRM_AGREEMENT_BUTTON_TEXT)]],
            ),
            parse_mode="HTML",
        )
        await state.update_data(user_id=user.user_id)
        await state.set_state(_BLOGGER_AGREEMENTS_STATE)
        return

    if not await offer_response_rate_limiter.allow_async(user.external_id):
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Слишком много запросов. Попробуйте позже.",
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
        await _send_order_closed_and_remove_keyboard(incoming, messenger_client)
        return

    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text="Отклик принят! Ожидайте связи от рекламодателя.",
    )

    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )

    if result.order.product_link:
        await messenger_client.send_text(
            chat_id=incoming.chat_id, text=result.order.product_link
        )
    await messenger_client.send_text(
        chat_id=incoming.chat_id, text=BLOGGER_AFTER_RESPONSE_WHAT_NEXT
    )

    # Send contact immediately after each response
    await _send_contact_immediately(
        order=result.order,
        blogger_id=user.user_id,
        response_count=result.response_count,
        user_role_service=user_role_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
    )


def _format_ugc_type(order: Order) -> str:
    """Return human-readable order/format type for advertiser message."""
    if order.order_type.value == "ugc_plus_placement":
        return "UGC + размещение"
    return "UGC-видео для бренда"


async def _send_contact_immediately(
    order: Order,
    blogger_id: UUID,
    response_count: int,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    interaction_service: InteractionService | None,
    messenger_client: MessengerClient,
) -> None:
    """Send contact to advertiser after each response (TZ format)."""

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

    # Create interaction for feedback tracking (72 hour timer starts)
    if interaction_service:
        await interaction_service.create_for_contacts_sent(
            order_id=order.order_id,
            blogger_id=blogger_id,
            advertiser_id=order.advertiser_id,
        )
