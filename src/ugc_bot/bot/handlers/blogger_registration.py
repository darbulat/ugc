"""Blogger registration flow handlers."""

import logging
import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message

from ugc_bot.application.errors import BloggerRegistrationError, UserNotFoundError
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import cancel_keyboard, with_cancel_keyboard
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserRole, UserStatus


router = Router()
logger = logging.getLogger(__name__)

_INSTAGRAM_URL_REGEX = re.compile(
    r"^(https?://)?(www\.)?instagram\.com/[A-Za-z0-9._]+/?$"
)


class BloggerRegistrationStates(StatesGroup):
    """States for blogger registration."""

    name = State()
    instagram = State()
    topics = State()
    audience_gender = State()
    audience_age = State()
    audience_geo = State()
    price = State()
    agreements = State()


@router.message(Command("register"))
async def start_registration(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
) -> None:
    """Start blogger registration flow."""

    if message.from_user is None:
        return

    user = user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None or user.role not in {UserRole.BLOGGER, UserRole.BOTH}:
        await message.answer("Please choose role 'Я блогер' first.")
        return
    if user.status == UserStatus.BLOCKED:
        await message.answer("Заблокированные пользователи не могут регистрироваться.")
        return
    if user.status == UserStatus.PAUSE:
        await message.answer("Пользователи на паузе не могут регистрироваться.")
        return
    if user.status == UserStatus.BLOCKED:
        await message.answer("Заблокированные пользователи не могут регистрироваться.")
        return
    if user.status == UserStatus.PAUSE:
        await message.answer("Пользователи на паузе не могут регистрироваться.")
        return

    await state.update_data(
        user_id=user.user_id,
        external_id=str(message.from_user.id),
        role=user.role,
    )
    await message.answer(
        "Введите ваш ник / имя для профиля:",
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(BloggerRegistrationStates.name)


@router.message(BloggerRegistrationStates.name)
async def handle_name(message: Message, state: FSMContext) -> None:
    """Store nickname."""

    nickname = (message.text or "").strip()
    if not nickname:
        await message.answer("Ник не может быть пустым. Введите снова:")
        return

    await state.update_data(nickname=nickname)
    await message.answer("Введите ссылку на Instagram:", reply_markup=cancel_keyboard())
    await state.set_state(BloggerRegistrationStates.instagram)


@router.message(BloggerRegistrationStates.instagram)
async def handle_instagram(message: Message, state: FSMContext) -> None:
    """Store Instagram URL."""

    instagram_url = (message.text or "").strip()
    if not instagram_url:
        await message.answer("Ссылка не может быть пустой. Введите снова:")
        return
    if not _INSTAGRAM_URL_REGEX.match(instagram_url):
        await message.answer(
            "Неверный формат ссылки Instagram. Пример: https://instagram.com/name"
        )
        return

    await state.update_data(instagram_url=instagram_url)
    topics_text = (
        "Выберите тематики через запятую:\n"
        "fitness, beauty, travel, food, fashion, kids, tech, other"
    )
    await message.answer(topics_text, reply_markup=cancel_keyboard())
    await state.set_state(BloggerRegistrationStates.topics)


@router.message(BloggerRegistrationStates.topics)
async def handle_topics(message: Message, state: FSMContext) -> None:
    """Store blogger topics."""

    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Введите хотя бы одну тему:")
        return

    topics = [topic.strip().lower() for topic in raw.split(",") if topic.strip()]
    await state.update_data(topics={"selected": topics})

    await message.answer(
        "Укажите пол ЦА:",
        reply_markup=with_cancel_keyboard(
            keyboard=[
                [KeyboardButton(text="м")],
                [KeyboardButton(text="ж")],
                [KeyboardButton(text="все")],
            ],
        ),
    )
    await state.set_state(BloggerRegistrationStates.audience_gender)


@router.message(BloggerRegistrationStates.audience_gender)
async def handle_gender(message: Message, state: FSMContext) -> None:
    """Store audience gender."""

    gender_text = (message.text or "").strip().lower()
    gender_map = {
        "м": AudienceGender.MALE,
        "ж": AudienceGender.FEMALE,
        "все": AudienceGender.ALL,
    }
    if gender_text not in gender_map:
        await message.answer("Выберите 'м', 'ж' или 'все'.")
        return

    await state.update_data(audience_gender=gender_map[gender_text])
    await message.answer(
        "Введите возрастной диапазон, например 18-35:",
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(BloggerRegistrationStates.audience_age)


@router.message(BloggerRegistrationStates.audience_age)
async def handle_age(message: Message, state: FSMContext) -> None:
    """Store audience age range."""

    raw = (message.text or "").strip()
    try:
        min_age, max_age = _parse_age_range(raw)
    except ValueError:
        await message.answer("Введите диапазон в формате 18-35.")
        return

    await state.update_data(audience_age_min=min_age, audience_age_max=max_age)
    await message.answer(
        "Введите географию ЦА (страна / город):",
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(BloggerRegistrationStates.audience_geo)


@router.message(BloggerRegistrationStates.audience_geo)
async def handle_geo(message: Message, state: FSMContext) -> None:
    """Store audience geography."""

    geo = (message.text or "").strip()
    if not geo:
        await message.answer("География не может быть пустой. Введите снова:")
        return

    await state.update_data(audience_geo=geo)
    await message.answer("Введите цену за 1 UGC-видео:", reply_markup=cancel_keyboard())
    await state.set_state(BloggerRegistrationStates.price)


@router.message(BloggerRegistrationStates.price)
async def handle_price(message: Message, state: FSMContext) -> None:
    """Store price."""

    raw = (message.text or "").replace(",", ".").strip()
    try:
        price = float(raw)
    except ValueError:
        await message.answer("Введите число, например 1500.")
        return

    if price <= 0:
        await message.answer("Цена должна быть больше 0.")
        return

    await state.update_data(price=price)
    await message.answer(
        "Подтвердите согласие с офертой и политиками: напишите 'Согласен'.",
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(BloggerRegistrationStates.agreements)


@router.message(BloggerRegistrationStates.agreements)
async def handle_agreements(
    message: Message,
    state: FSMContext,
    blogger_registration_service: BloggerRegistrationService,
    user_role_service: UserRoleService,
) -> None:
    """Finalize registration after agreements."""

    agreement = (message.text or "").strip().lower()
    if agreement != "согласен":
        await message.answer("Нужно согласие. Напишите 'Согласен'.")
        return

    data = await state.get_data()
    try:
        user_role_service.set_role(
            external_id=data["external_id"],
            messenger_type=MessengerType.TELEGRAM,
            username=data["nickname"],
            role=data["role"],
        )
        profile = blogger_registration_service.register_blogger(
            user_id=data["user_id"],
            instagram_url=data["instagram_url"],
            topics=data["topics"],
            audience_gender=data["audience_gender"],
            audience_age_min=data["audience_age_min"],
            audience_age_max=data["audience_age_max"],
            audience_geo=data["audience_geo"],
            price=data["price"],
        )
    except (BloggerRegistrationError, UserNotFoundError) as exc:
        logger.warning(
            "Blogger registration failed",
            extra={"user_id": data.get("user_id"), "reason": str(exc)},
        )
        await message.answer(f"Ошибка регистрации: {exc}")
        return
    except Exception:
        logger.exception(
            "Unexpected error during blogger registration",
            extra={"user_id": data.get("user_id")},
        )
        await message.answer("Произошла неожиданная ошибка. Попробуйте позже.")
        return

    await state.clear()
    await message.answer(
        "Профиль создан. Статус подтверждения Instagram: НЕ ПОДТВЕРЖДЁН.\n"
        f"Ваш Instagram: {profile.instagram_url}"
    )


def _parse_age_range(value: str) -> tuple[int, int]:
    """Parse age range input like '18-35'."""

    parts = value.replace(" ", "").split("-")
    if len(parts) != 2:
        raise ValueError("Invalid range")
    min_age = int(parts[0])
    max_age = int(parts[1])
    if min_age <= 0 or max_age <= 0:
        raise ValueError("Invalid ages")
    if max_age < min_age:
        raise ValueError("Invalid range")
    return min_age, max_age
