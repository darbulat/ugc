"""Handlers for offer responses."""

import logging
from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.security_warnings import (
    ADVERTISER_CONTACTS_WARNING,
    BLOGGER_RESPONSE_WARNING,
)
from ugc_bot.bot.handlers.utils import RateLimiter, send_with_retry
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import MessengerType, UserStatus


router = Router()
logger = logging.getLogger(__name__)
_rate_limiter = RateLimiter(limit=5, window_seconds=10.0)
_send_retries = 3
_send_retry_delay_seconds = 0.5


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

    if callback.from_user is None:
        return

    user = await user_role_service.get_user(
        external_id=str(callback.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await callback.answer("Пользователь не найден.")
        return
    if user.status == UserStatus.BLOCKED:
        await callback.answer("Заблокированные пользователи не могут откликаться.")
        return
    if user.status == UserStatus.PAUSE:
        await callback.answer("Пользователи на паузе не могут откликаться.")
        return
    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        await callback.answer("Профиль блогера не заполнен. Команда: /register")
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
    result = await offer_response_service.respond_and_finalize(order_id, user.user_id)

    await callback.answer("Отклик принят! Ожидайте связи от рекламодателя.")
    if callback.message:
        await callback.message.answer(
            "Ваш отклик сохранен. Рекламодатель свяжется с вами."
        )
        # Send security warning
        await callback.message.answer(BLOGGER_RESPONSE_WARNING)

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


async def _send_contact_immediately(
    order: Order,
    blogger_id: UUID,
    response_count: int,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    interaction_service: InteractionService | None,
    bot,
) -> None:
    """Send contact to advertiser immediately after each response."""

    # Get blogger info
    user = await user_role_service.get_user_by_id(blogger_id)
    profile = await profile_service.get_blogger_profile(blogger_id)
    if user is None or profile is None:
        logger.warning(
            "Cannot send contact: user or profile not found",
            extra={"order_id": order.order_id, "blogger_id": blogger_id},
        )
        return

    # Format contact info
    handle = f"@{user.username}" if user.username else user.external_id
    contact_text = (
        f"Новый отклик по заказу #{order.order_id}:\n"
        f"Ник: {handle}\n"
        f"Telegram: {user.external_id}\n"
        f"Instagram: {profile.instagram_url}\n"
        f"Цена: {profile.price}\n"
        f"Статус: {'Подтверждён' if profile.confirmed else 'Не подтверждён'}"
    )

    # Send to advertiser
    advertiser = await user_role_service.get_user_by_id(order.advertiser_id)
    if advertiser and bot and advertiser.external_id.isdigit():
        await send_with_retry(
            bot,
            chat_id=int(advertiser.external_id),
            text=contact_text,
            retries=_send_retries,
            delay_seconds=_send_retry_delay_seconds,
            logger=logger,
            extra={"order_id": str(order.order_id)},
        )
        # Send security warning only on first contact
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
