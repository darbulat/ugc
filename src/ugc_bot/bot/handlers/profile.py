"""Profile view handlers."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.domain.enums import MessengerType, UserRole


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

    parts = [
        "Ваш профиль:",
        f"Username: {user.username}",
        f"Role: {user.role.value}",
        f"Status: {user.status.value}",
    ]

    if user.role in {UserRole.BLOGGER, UserRole.BOTH}:
        blogger = profile_service.get_blogger_profile(user.user_id)
        if blogger is None:
            parts.append("Профиль блогера не заполнен. Команда: /register")
        else:
            topics = ", ".join(blogger.topics.get("selected", []))
            confirmed = "Да" if blogger.confirmed else "Нет"
            parts.extend(
                [
                    "Блогер:",
                    f"Instagram: {blogger.instagram_url}",
                    f"Подтвержден: {confirmed}",
                    f"Тематики: {topics or '—'}",
                    f"ЦА: {blogger.audience_gender.value} {blogger.audience_age_min}-{blogger.audience_age_max}",
                    f"Гео: {blogger.audience_geo}",
                    f"Цена: {blogger.price}",
                ]
            )

    if user.role in {UserRole.ADVERTISER, UserRole.BOTH}:
        advertiser = profile_service.get_advertiser_profile(user.user_id)
        if advertiser is None:
            parts.append("Профиль рекламодателя не заполнен. Команда: /register_advertiser")
        else:
            parts.extend(
                [
                    "Рекламодатель:",
                    f"Контакт: {advertiser.contact}",
                ]
            )

    await message.answer("\n".join(parts))
