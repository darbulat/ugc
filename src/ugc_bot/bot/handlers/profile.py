"""Profile view handlers."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.bot.handlers.keyboards import (
    advertiser_menu_keyboard,
    blogger_menu_keyboard,
)
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

    blogger = profile_service.get_blogger_profile(user.user_id)
    advertiser = profile_service.get_advertiser_profile(user.user_id)
    roles: list[str] = []
    if user.role == UserRole.BOTH:
        roles.extend(["blogger", "advertiser"])
    elif user.role == UserRole.BLOGGER:
        roles.append("blogger")
    elif user.role == UserRole.ADVERTISER:
        roles.append("advertiser")
    else:
        roles.append("—")
    parts = [
        "Ваш профиль:",
        f"Username: {user.username}",
        f"Roles: {', '.join(roles)}",
        f"Status: {user.status.value}",
    ]

    if blogger is None and user.role in {UserRole.BLOGGER, UserRole.BOTH}:
        parts.append("Профиль блогера не заполнен. Команда: /register")
    elif blogger is not None:
        topics = ", ".join((blogger.topics or {}).get("selected", []))
        confirmed = "Да" if blogger.confirmed else "Нет"
        audience_gender = (
            blogger.audience_gender.value if blogger.audience_gender else "—"
        )
        audience_age_min = (
            str(blogger.audience_age_min)
            if blogger.audience_age_min is not None
            else "—"
        )
        audience_age_max = (
            str(blogger.audience_age_max)
            if blogger.audience_age_max is not None
            else "—"
        )
        parts.extend(
            [
                "Блогер:",
                f"Instagram: {blogger.instagram_url}",
                f"Подтвержден: {confirmed}",
                f"Тематики: {topics or '—'}",
                f"ЦА: {audience_gender} {audience_age_min}-{audience_age_max}",
                f"Гео: {blogger.audience_geo}",
                f"Цена: {blogger.price}",
            ]
        )

    if advertiser is None and user.role in {UserRole.ADVERTISER, UserRole.BOTH}:
        parts.append("Профиль рекламодателя не заполнен. Команда: /register_advertiser")
    elif advertiser is not None:
        advertiser_instagram = (
            advertiser.instagram_url if advertiser.instagram_url else "—"
        )
        advertiser_confirmed = "Да" if advertiser.confirmed else "Нет"
        parts.extend(
            [
                "Рекламодатель:",
                f"Instagram: {advertiser_instagram}",
                f"Подтвержден: {advertiser_confirmed}",
                f"Контакт: {advertiser.contact}",
            ]
        )

    # Show appropriate keyboard based on role
    reply_markup = None
    if blogger is not None:
        reply_markup = blogger_menu_keyboard(confirmed=blogger.confirmed)
    elif advertiser is not None:
        reply_markup = advertiser_menu_keyboard()

    await message.answer("\n".join(parts), reply_markup=reply_markup)
