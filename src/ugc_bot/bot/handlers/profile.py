"""Profile view and edit handlers."""

import logging
import re
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    EDIT_PROFILE_BUTTON_TEXT,
    advertiser_menu_keyboard,
    blogger_profile_view_keyboard,
    support_keyboard,
    with_support_keyboard,
)
from ugc_bot.domain.enums import AudienceGender, MessengerType, WorkFormat


router = Router()
logger = logging.getLogger(__name__)

_INSTAGRAM_URL_REGEX = re.compile(
    r"^(https?://)?(www\.)?instagram\.com/[A-Za-z0-9._]+/?$"
)

_EDIT_FIELDS = [
    ("Имя/ник", "nickname"),
    ("Instagram", "instagram_url"),
    ("Город", "city"),
    ("Тематики", "topics"),
    ("Пол аудитории", "audience_gender"),
    ("Возраст аудитории", "audience_age"),
    ("География аудитории", "audience_geo"),
    ("Цена", "price"),
    ("Бартер", "barter"),
    ("Формат работы", "work_format"),
]
EDIT_FIELD_LABELS = [label for label, _ in _EDIT_FIELDS]
EDIT_FIELD_KEYS = {label: key for label, key in _EDIT_FIELDS}

_AGE_BUTTONS: dict[str, tuple[int, int]] = {
    "до 18": (0, 17),
    "18–24": (18, 24),
    "25–34": (25, 34),
    "35–44": (35, 44),
    "45+": (45, 99),
}


class EditProfileStates(StatesGroup):
    """States for editing blogger profile."""

    choosing_field = State()
    entering_value = State()


@router.message(Command("profile"))
@router.message(lambda msg: (msg.text or "").strip() == "Мой профиль")
async def show_profile(message: Message, profile_service: ProfileService) -> None:
    """Show current user's profile."""

    if message.from_user is None:
        return

    user = await profile_service.get_user_by_external(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await message.answer("Профиль не найден. Выберите роль через /role.")
        return

    blogger = await profile_service.get_blogger_profile(user.user_id)
    advertiser = await profile_service.get_advertiser_profile(user.user_id)
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
        confirmed = "Да" if blogger.confirmed else "Нет"
        barter_str = "Да" if blogger.barter else "Нет"
        work_fmt = (
            "Размещать рекламу у себя в аккаунте"
            if blogger.work_format == WorkFormat.ADS_IN_ACCOUNT
            else "Только UGC"
        )
        parts.extend(
            [
                "Блогер:",
                f"Instagram: {blogger.instagram_url}",
                f"Подтвержден: {confirmed}",
                f"Город: {blogger.city}",
                f"Тематики: {topics or '—'}",
                f"ЦА: {blogger.audience_gender.value} {blogger.audience_age_min}-{blogger.audience_age_max}",
                f"Гео: {blogger.audience_geo}",
                f"Цена: {blogger.price}",
                f"Бартер: {barter_str}",
                f"Формат работы: {work_fmt}",
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
        reply_markup = blogger_profile_view_keyboard(confirmed=blogger.confirmed)
    elif advertiser is not None:
        reply_markup = advertiser_menu_keyboard()

    await message.answer("\n".join(parts), reply_markup=reply_markup)


def _edit_field_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard with profile field names for editing (two per row to save space)."""

    rows = []
    for i in range(0, len(EDIT_FIELD_LABELS), 2):
        row = [KeyboardButton(text=EDIT_FIELD_LABELS[i])]
        if i + 1 < len(EDIT_FIELD_LABELS):
            row.append(KeyboardButton(text=EDIT_FIELD_LABELS[i + 1]))
        rows.append(row)
    rows.append([KeyboardButton(text="Мой профиль")])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        one_time_keyboard=False,
    )


@router.message(lambda msg: (msg.text or "").strip() == EDIT_PROFILE_BUTTON_TEXT)
async def edit_profile_start(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """Show field selection for profile edit."""

    if message.from_user is None:
        return

    user = await profile_service.get_user_by_external(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await message.answer("Профиль не найден. Выберите роль через /role.")
        return

    blogger = await profile_service.get_blogger_profile(user.user_id)
    if blogger is None:
        await message.answer("Профиль блогера не заполнен.")
        return

    await state.update_data(
        edit_user_id=user.user_id, edit_external_id=str(message.from_user.id)
    )
    await message.answer(
        "Выберите раздел для редактирования:",
        reply_markup=_edit_field_keyboard(),
    )
    await state.set_state(EditProfileStates.choosing_field)


@router.message(EditProfileStates.choosing_field)
async def edit_profile_choose_field(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    blogger_registration_service: BloggerRegistrationService,
    user_role_service: UserRoleService,
) -> None:
    """Handle field choice and ask for new value."""

    text = (message.text or "").strip()
    if text == "Мой профиль":
        await state.clear()
        await show_profile(message, profile_service)
        return

    if text not in EDIT_FIELD_KEYS:
        await message.answer("Выберите один из разделов на клавиатуре.")
        return

    field_key = EDIT_FIELD_KEYS[text]
    await state.update_data(editing_field=field_key)

    prompts = {
        "nickname": "Введите новое имя или ник:",
        "instagram_url": "Прикрепите новую ссылку в формате instagram.com/name:",
        "city": "Из какого вы города?",
        "topics": "Напишите 1–3 тематики через запятую:",
        "audience_gender": "Кто в основном смотрит ваш контент?",
        "audience_age": "Основной возраст вашей аудитории?",
        "audience_geo": "Укажите до 3 городов через запятую:",
        "price": "Укажите цену за 1 UGC‑видео в рублях:",
        "barter": "Готовы работать по бартеру?",
        "work_format": "Как готовы работать с брендами?",
    }
    prompt = prompts.get(field_key, "Введите новое значение:")

    if field_key == "audience_gender":
        await message.answer(
            prompt,
            reply_markup=with_support_keyboard(
                keyboard=[
                    [KeyboardButton(text="В основном женщины")],
                    [KeyboardButton(text="В основном мужчины")],
                    [KeyboardButton(text="Примерно поровну")],
                ],
            ),
        )
    elif field_key == "audience_age":
        await message.answer(
            prompt,
            reply_markup=with_support_keyboard(
                keyboard=[
                    [KeyboardButton(text="до 18")],
                    [KeyboardButton(text="18–24")],
                    [KeyboardButton(text="25–34")],
                    [KeyboardButton(text="35–44")],
                    [KeyboardButton(text="45+")],
                ],
            ),
        )
    elif field_key == "barter":
        await message.answer(
            prompt,
            reply_markup=with_support_keyboard(
                keyboard=[
                    [KeyboardButton(text="Да")],
                    [KeyboardButton(text="Нет")],
                ],
            ),
        )
    elif field_key == "work_format":
        await message.answer(
            prompt,
            reply_markup=with_support_keyboard(
                keyboard=[
                    [KeyboardButton(text="Размещать рекламу у себя в аккаунте")],
                    [KeyboardButton(text="Только UGC")],
                ],
            ),
        )
    else:
        await message.answer(prompt, reply_markup=support_keyboard())

    await state.set_state(EditProfileStates.entering_value)


@router.message(EditProfileStates.entering_value)
async def edit_profile_enter_value(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    blogger_registration_service: BloggerRegistrationService,
    user_role_service: UserRoleService,
) -> None:
    """Validate and save new field value, then show profile."""

    data = await state.get_data()
    field_key = data.get("editing_field")
    user_id_raw = data.get("edit_user_id")
    external_id_raw = data.get("edit_external_id")
    if not field_key or not user_id_raw or not external_id_raw:
        await state.clear()
        await message.answer("Сессия истекла. Откройте «Мой профиль» снова.")
        return
    external_id = str(external_id_raw)

    user_id = UUID(user_id_raw) if isinstance(user_id_raw, str) else user_id_raw
    blogger = await profile_service.get_blogger_profile(user_id)
    if blogger is None:
        await state.clear()
        await message.answer("Профиль не найден.")
        return

    text = (message.text or "").strip()

    if field_key == "nickname":
        if not text:
            await message.answer("Имя не может быть пустым.")
            return
        await user_role_service.set_user(
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM,
            username=text,
        )
        await state.clear()
        await message.answer("Имя обновлено.")
        await show_profile(message, profile_service)
        return

    if field_key == "instagram_url":
        if not text or "instagram.com/" not in text.lower():
            await message.answer("Неверный формат ссылки. Пример: instagram.com/name")
            return
        if not _INSTAGRAM_URL_REGEX.match(text):
            await message.answer("Неверный формат ссылки Instagram.")
            return
        existing = await blogger_registration_service.get_profile_by_instagram_url(text)
        if existing is not None and existing.user_id != user_id:
            await message.answer(
                "Этот Instagram аккаунт уже зарегистрирован. Используйте другой."
            )
            return
        updated = await blogger_registration_service.update_blogger_profile(
            user_id, instagram_url=text
        )
    elif field_key == "city":
        if not text:
            await message.answer("Город не может быть пустым.")
            return
        updated = await blogger_registration_service.update_blogger_profile(
            user_id, city=text
        )
    elif field_key == "topics":
        if not text:
            await message.answer("Введите хотя бы одну тематику.")
            return
        topics = [t.strip().lower() for t in text.split(",") if t.strip()]
        if not topics:
            await message.answer("Введите хотя бы одну тематику.")
            return
        updated = await blogger_registration_service.update_blogger_profile(
            user_id, topics={"selected": topics}
        )
    elif field_key == "audience_gender":
        key = text.lower()
        gender_map = {
            "в основном женщины": AudienceGender.FEMALE,
            "в основном мужчины": AudienceGender.MALE,
            "примерно поровну": AudienceGender.ALL,
        }
        if key not in gender_map:
            await message.answer("Выберите одну из кнопок.")
            return
        updated = await blogger_registration_service.update_blogger_profile(
            user_id, audience_gender=gender_map[key]
        )
    elif field_key == "audience_age":
        if text not in _AGE_BUTTONS:
            await message.answer("Выберите одну из кнопок возраста.")
            return
        min_age, max_age = _AGE_BUTTONS[text]
        updated = await blogger_registration_service.update_blogger_profile(
            user_id, audience_age_min=min_age, audience_age_max=max_age
        )
    elif field_key == "audience_geo":
        if not text:
            await message.answer("Укажите хотя бы один город.")
            return
        cities = [c.strip() for c in text.split(",") if c.strip()]
        if len(cities) > 3:
            await message.answer("Укажите не более 3 городов.")
            return
        updated = await blogger_registration_service.update_blogger_profile(
            user_id, audience_geo=text
        )
    elif field_key == "price":
        try:
            price = float(text.replace(",", "."))
        except ValueError:
            await message.answer("Введите число, например 1000.")
            return
        if price <= 0:
            await message.answer("Цена должна быть больше 0.")
            return
        updated = await blogger_registration_service.update_blogger_profile(
            user_id, price=price
        )
    elif field_key == "barter":
        if text.lower() == "да":
            barter = True
        elif text.lower() == "нет":
            barter = False
        else:
            await message.answer("Выберите Да или Нет.")
            return
        updated = await blogger_registration_service.update_blogger_profile(
            user_id, barter=barter
        )
    elif field_key == "work_format":
        if text == "Размещать рекламу у себя в аккаунте":
            wf = WorkFormat.ADS_IN_ACCOUNT
        elif text == "Только UGC":
            wf = WorkFormat.UGC_ONLY
        else:
            await message.answer("Выберите одну из кнопок.")
            return
        updated = await blogger_registration_service.update_blogger_profile(
            user_id, work_format=wf
        )
    else:
        await state.clear()
        await message.answer("Неизвестное поле.")
        return

    if updated is None:
        await state.clear()
        await message.answer("Не удалось обновить профиль.")
        return

    await state.clear()
    await message.answer(
        "Профиль обновлён.",
        reply_markup=blogger_profile_view_keyboard(updated.confirmed),
    )
    await show_profile(message, profile_service)
