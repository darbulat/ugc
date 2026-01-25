"""Profile view handlers."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.bot.handlers.keyboards import (
    advertiser_menu_keyboard,
    blogger_menu_keyboard,
)
from ugc_bot.domain.enums import MessengerType


router = Router()


@router.message(Command("profile"))
@router.message(lambda msg: (msg.text or "").strip() == "Мой профиль")
async def show_profile(message: Message, profile_service: ProfileService) -> None:
    """Show current user's profile."""

    if message.from_user is None:
        return

    user = profile_service.get_user_by_external(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await message.answer("Профиль не найден. Выберите роль через /role.")
        return

    blogger = profile_service.get_blogger_profile(user.user_id)
    advertiser = profile_service.get_advertiser_profile(user.user_id)
    roles: list[str] = []
    if blogger is not None:
        roles.append("blogger")
    if advertiser is not None:
        roles.append("advertiser")
    if not roles:
        roles.append("—")
    parts = [
        "Ваш профиль:",
        f"Username: {user.username}",
        f"Roles: {', '.join(roles)}",
        f"Status: {user.status.value}",
    ]

    if blogger is None:
        parts.append("Профиль блогера не заполнен. Команда: /register")
    else:
        topics = ", ".join(blogger.topics.get("selected", []))
        confirmed = "Да" if user.confirmed else "Нет"
        instagram_info = (
            user.instagram_url if user.instagram_url else blogger.instagram_url
        )
        parts.extend(
            [
                "Блогер:",
                f"Instagram: {instagram_info}",
                f"Подтвержден: {confirmed}",
                f"Тематики: {topics or '—'}",
                f"ЦА: {blogger.audience_gender.value} {blogger.audience_age_min}-{blogger.audience_age_max}",
                f"Гео: {blogger.audience_geo}",
                f"Цена: {blogger.price}",
            ]
        )

    if advertiser is None:
        parts.append("Профиль рекламодателя не заполнен. Команда: /register_advertiser")
    else:
        parts.extend(
            [
                "Рекламодатель:",
                f"Контакт: {advertiser.contact}",
            ]
        )

    # Show appropriate keyboard based on role
    reply_markup = None
    if blogger is not None:
        reply_markup = blogger_menu_keyboard(confirmed=user.confirmed)
    elif advertiser is not None:
        reply_markup = advertiser_menu_keyboard()

    await message.answer("\n".join(parts), reply_markup=reply_markup)
