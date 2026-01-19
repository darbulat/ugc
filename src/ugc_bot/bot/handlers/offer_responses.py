"""Handlers for offer responses."""

import logging
from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from ugc_bot.application.errors import OrderCreationError
from datetime import datetime, timezone

from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus


router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("offer:")
)
async def handle_offer_response(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    offer_response_service: OfferResponseService,
) -> None:
    """Handle blogger response to offer."""

    if callback.from_user is None:
        return

    user = user_role_service.get_user(
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
    blogger_profile = profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        await callback.answer("Профиль блогера не заполнен. Команда: /register")
        return
    if not blogger_profile.confirmed:
        await callback.answer("Подтвердите Instagram перед откликом.")
        return

    raw = callback.data.split("offer:", 1)[-1] if callback.data else ""
    try:
        order_id = UUID(raw)
    except ValueError:
        await callback.answer("Неверный идентификатор заказа.")
        return

    order = offer_response_service.order_repo.get_by_id(order_id)
    if order is None:
        await callback.answer("Заказ не найден.")
        return
    if order.status != OrderStatus.ACTIVE:
        await callback.answer("Заказ не активен.")
        return
    if offer_response_service.response_repo.exists(order_id, user.user_id):
        await callback.answer("Вы уже откликались на этот заказ.")
        return
    if (
        offer_response_service.response_repo.count_by_order(order_id)
        >= order.bloggers_needed
    ):
        await callback.answer("Лимит откликов по заказу достигнут.")
        return

    try:
        offer_response_service.respond(order_id, user.user_id)
    except OrderCreationError as exc:
        logger.warning(
            "Offer response rejected",
            extra={"user_id": user.user_id, "reason": str(exc)},
        )
        await callback.answer(str(exc))
        return
    except Exception:
        logger.exception(
            "Unexpected offer response error",
            extra={"user_id": user.user_id},
        )
        await callback.answer("Произошла ошибка. Попробуйте позже.")
        return

    await callback.answer("Отклик принят! Ожидайте связи от рекламодателя.")
    if callback.message:
        await callback.message.answer(
            "Ваш отклик сохранен. Рекламодатель свяжется с вами."
        )

    await _maybe_send_contacts_and_close(
        order_id=order_id,
        offer_response_service=offer_response_service,
        user_role_service=user_role_service,
        profile_service=profile_service,
        bot=callback.message.bot if callback.message else None,
    )


async def _maybe_send_contacts_and_close(
    order_id: UUID,
    offer_response_service: OfferResponseService,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    bot,
) -> None:
    """Send contacts to advertiser and close order when limit reached."""

    order = offer_response_service.order_repo.get_by_id(order_id)
    if order is None:
        return
    if order.status != OrderStatus.ACTIVE:
        return
    if (
        offer_response_service.response_repo.count_by_order(order_id)
        < order.bloggers_needed
    ):
        return

    responses = offer_response_service.response_repo.list_by_order(order_id)
    contacts: list[str] = []
    for response in responses:
        user = user_role_service.get_user_by_id(response.blogger_id)
        profile = profile_service.get_blogger_profile(response.blogger_id)
        if user is None or profile is None:
            continue
        handle = f"@{user.username}" if user.username else user.external_id
        contacts.append(
            f"{handle} | Instagram: {profile.instagram_url} | Цена: {profile.price}"
        )

    if contacts:
        advertiser = user_role_service.get_user_by_id(order.advertiser_id)
        if advertiser and bot and advertiser.external_id.isdigit():
            await bot.send_message(
                chat_id=int(advertiser.external_id),
                text="Контакты блогеров:\n" + "\n".join(contacts),
            )

    closed = Order(
        order_id=order.order_id,
        advertiser_id=order.advertiser_id,
        product_link=order.product_link,
        offer_text=order.offer_text,
        ugc_requirements=order.ugc_requirements,
        barter_description=order.barter_description,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=OrderStatus.CLOSED,
        created_at=order.created_at,
        contacts_sent_at=datetime.now(timezone.utc),
    )
    offer_response_service.order_repo.save(closed)
