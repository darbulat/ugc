"""Handlers for offer responses."""

import contextlib
import logging
from uuid import UUID

from aiogram import Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.security_warnings import (
    ADVERTISER_CONTACTS_WARNING,
    ADVERTISER_NEW_RESPONSE_WHAT_NEXT,
    BLOGGER_AFTER_RESPONSE_WHAT_NEXT,
)
from ugc_bot.bot.handlers.utils import (
    RateLimiter,
    get_user_and_ensure_allowed_callback,
    send_with_retry,
)
from ugc_bot.domain.entities import Order

router = Router()
logger = logging.getLogger(__name__)
_rate_limiter = RateLimiter(limit=5, window_seconds=10.0)
_send_retries = 3
_send_retry_delay_seconds = 0.5


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("offer_skip:")
)
async def handle_offer_skip(callback: CallbackQuery) -> None:
    """Handle blogger pressing 'Пропустить' on offer (no response recorded).

    Removes inline keyboard so 'Готов снять UGC' can no longer be pressed.
    """
    await callback.answer("Ок, пропущено.")
    msg = callback.message
    edit_reply_markup = getattr(msg, "edit_reply_markup", None) if msg else None
    if (
        msg
        and getattr(msg, "reply_markup", None)
        and callable(edit_reply_markup)
    ):
        with contextlib.suppress(Exception):
            await edit_reply_markup(reply_markup=None)


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("offer:")
)
async def handle_offer_response(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    offer_response_service: OfferResponseService,
    interaction_service: InteractionService,
) -> None:
    """Handle blogger response to offer."""

    user = await get_user_and_ensure_allowed_callback(
        callback,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Заблокированные пользователи не могут откликаться.",
        pause_msg="Пользователи на паузе не могут откликаться.",
    )
    if user is None:
        return
    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        await callback.answer("Профиль блогера не заполнен. Команда: /creator")
        return
    if not blogger_profile.confirmed:
        await callback.answer("Подтвердите Instagram перед откликом.")
        return

    if not _rate_limiter.allow(user.external_id):
        await callback.answer("Слишком много запросов. Попробуйте позже.")
        return

    raw = callback.data.split("offer:", 1)[-1] if callback.data else ""
    try:
        order_id = UUID(raw)
    except ValueError:
        await callback.answer("Неверный идентификатор заказа.")
        return

    # Middleware handles OrderCreationError and other exceptions
    result = await offer_response_service.respond_and_finalize(
        order_id, user.user_id
    )

    await callback.answer("Отклик принят! Ожидайте связи от рекламодателя.")

    # Remove inline keyboard so buttons can no longer be pressed
    msg = callback.message
    edit_reply_markup = getattr(msg, "edit_reply_markup", None) if msg else None
    if (
        msg
        and getattr(msg, "reply_markup", None)
        and callable(edit_reply_markup)
    ):
        with contextlib.suppress(Exception):
            await edit_reply_markup(reply_markup=None)

    if callback.message and callback.message.bot:
        if result.order.product_link:
            await callback.message.answer(result.order.product_link)
        await callback.message.answer(BLOGGER_AFTER_RESPONSE_WHAT_NEXT)

    # Send contact immediately after each response
    await _send_contact_immediately(
        order=result.order,
        blogger_id=user.user_id,
        response_count=result.response_count,
        user_role_service=user_role_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        bot=callback.message.bot if callback.message else None,
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
    bot,
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
    open_profile_kb = (
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔗 Открыть профиль", url=profile_url
                    )
                ]
            ]
        )
        if profile_url.startswith("http")
        else None
    )

    advertiser = await user_role_service.get_user_by_id(order.advertiser_id)
    if advertiser and bot and advertiser.external_id.isdigit():
        await send_with_retry(
            bot,
            chat_id=int(advertiser.external_id),
            text=contact_text,
            reply_markup=open_profile_kb,
            retries=_send_retries,
            delay_seconds=_send_retry_delay_seconds,
            logger=logger,
            extra={"order_id": str(order.order_id)},
        )
        if response_count == 1:
            await send_with_retry(
                bot,
                chat_id=int(advertiser.external_id),
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
