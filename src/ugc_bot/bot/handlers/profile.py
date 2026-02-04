"""Profile view and edit handlers."""

import logging
import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import handle_draft_choice, parse_user_id_from_state
from ugc_bot.bot.handlers.keyboards import (
    EDIT_PROFILE_BUTTON_TEXT,
    DRAFT_QUESTION_TEXT,
    MY_PROFILE_BUTTON_TEXT,
    WORK_FORMAT_ADS_BUTTON_TEXT,
    WORK_FORMAT_UGC_ONLY_BUTTON_TEXT,
    advertiser_menu_keyboard,
    blogger_profile_view_keyboard,
    draft_choice_keyboard,
    support_keyboard,
    with_support_keyboard,
)
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserStatus, WorkFormat


router = Router()

_USER_STATUS_LABELS: dict[UserStatus, str] = {
    UserStatus.NEW: "Новый",
    UserStatus.ACTIVE: "Активен",
    UserStatus.PAUSE: "На паузе",
    UserStatus.BLOCKED: "Заблокирован",
}

_AUDIENCE_GENDER_LABELS: dict[AudienceGender, str] = {
    AudienceGender.MALE: "Мужчины",
    AudienceGender.FEMALE: "Женщины",
    AudienceGender.ALL: "Все",
}

_ROLE_LABELS: dict[str, str] = {
    "blogger": "Блогер",
    "advertiser": "Рекламодатель",
}


def _format_profile_text(
    user: User,
    blogger: BloggerProfile | None,
    advertiser: AdvertiserProfile | None,
) -> str:
    """Format profile data for user-friendly display."""
    roles: list[str] = []
    if blogger is not None:
        roles.append(_ROLE_LABELS["blogger"])
    if advertiser is not None:
        roles.append(_ROLE_LABELS["advertiser"])
    if not roles:
        roles.append("—")

    status_label = _USER_STATUS_LABELS.get(user.status, user.status.value)
    name_display = user.username or "—"

    lines = [
        "👤 Ваш профиль",
        "",
        "📋 Общая информация",
        f"   Имя: {name_display}",
        f"   Роли: {', '.join(roles)}",
        f"   Статус: {status_label}",
    ]

    if blogger is None:
        lines.extend(["", "📸 Профиль блогера", "   Не заполнен"])
    else:
        topics = ", ".join(blogger.topics.get("selected", [])) or "—"
        confirmed = "Да" if blogger.confirmed else "Нет"
        barter_str = "Да" if blogger.barter else "Нет"
        work_fmt = (
            "Размещать рекламу у себя в аккаунте"
            if blogger.work_format == WorkFormat.ADS_IN_ACCOUNT
            else "Только UGC"
        )
        gender_label = _AUDIENCE_GENDER_LABELS.get(
            blogger.audience_gender, blogger.audience_gender.value
        )
        lines.extend(
            [
                "",
                "📸 Профиль блогера",
                f"   Instagram: {blogger.instagram_url}",
                f"   Подтверждён: {confirmed}",
                f"   Город: {blogger.city}",
                f"   Тематики: {topics}",
                f"   Целевая аудитория: {gender_label}, {blogger.audience_age_min}–{blogger.audience_age_max} лет",
                f"   География: {blogger.audience_geo}",
                f"   Цена: {blogger.price} ₽",
                f"   Бартер: {barter_str}",
                f"   Формат работы: {work_fmt}",
            ]
        )

    if advertiser is None:
        lines.extend(["", "🏢 Профиль рекламодателя", "   Не заполнен"])
    else:
        adv_lines = [
            "",
            "🏢 Профиль рекламодателя",
            f"   Телефон: {advertiser.phone}",
            f"   Бренд: {advertiser.brand}",
        ]
        if advertiser.site_link:
            adv_lines.append(f"   Сайт: {advertiser.site_link}")
        lines.extend(adv_lines)

    return "\n".join(lines)


logger = logging.getLogger(__name__)

_INSTAGRAM_URL_REGEX = re.compile(
    r"^(https?://)?(www\.)?instagram\.com/[A-Za-z0-9._]+/?$"
)

_EDIT_FIELDS = [
    ("Имя", "nickname"),
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

_EDIT_FIELDS_ADVERTISER = [
    ("Имя", "name"),
    ("Телефон", "phone"),
    ("Бренд", "brand"),
    ("Ссылка на сайт", "site_link"),
]
EDIT_FIELD_LABELS_ADVERTISER = [label for label, _ in _EDIT_FIELDS_ADVERTISER]
EDIT_FIELD_KEYS_ADVERTISER = {label: key for label, key in _EDIT_FIELDS_ADVERTISER}

_AGE_BUTTONS: dict[str, tuple[int, int]] = {
    "до 18": (1, 17),
    "18–24": (18, 24),
    "25–34": (25, 34),
    "35–44": (35, 44),
    "45+": (45, 99),
}


EDIT_PROFILE_FLOW_TYPE = "edit_profile"


class EditProfileStates(StatesGroup):
    """States for editing blogger or advertiser profile."""

    choosing_draft_restore = State()
    choosing_profile_type = State()
    choosing_field = State()
    entering_value = State()


@router.message(Command("profile"))
@router.message(lambda msg: (msg.text or "").strip() == MY_PROFILE_BUTTON_TEXT)
async def show_profile(
    message: Message, profile_service: ProfileService, state: FSMContext
) -> None:
    """Show current user's profile."""
    await state.clear()

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
    text = _format_profile_text(user, blogger, advertiser)

    reply_markup = None
    if blogger is not None:
        reply_markup = blogger_profile_view_keyboard(confirmed=blogger.confirmed)
    elif advertiser is not None:
        reply_markup = advertiser_menu_keyboard()

    await message.answer(text, reply_markup=reply_markup)


def _edit_field_keyboard(profile_type: str = "blogger") -> ReplyKeyboardMarkup:
    """Keyboard with profile field names for editing (two per row to save space)."""

    labels = (
        EDIT_FIELD_LABELS_ADVERTISER
        if profile_type == "advertiser"
        else EDIT_FIELD_LABELS
    )
    rows = []
    for i in range(0, len(labels), 2):
        row = [KeyboardButton(text=labels[i])]
        if i + 1 < len(labels):
            row.append(KeyboardButton(text=labels[i + 1]))
        rows.append(row)
    rows.append([KeyboardButton(text=MY_PROFILE_BUTTON_TEXT)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def _edit_profile_type_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard to choose blogger or advertiser profile to edit."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Редактировать профиль блогера")],
            [KeyboardButton(text="Редактировать профиль рекламодателя")],
            [KeyboardButton(text=MY_PROFILE_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


@router.message(lambda msg: (msg.text or "").strip() == EDIT_PROFILE_BUTTON_TEXT)
async def edit_profile_start(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Show field selection for profile edit, or draft restore choice."""

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
    if blogger is None and advertiser is None:
        await message.answer("Профиль не заполнен.")
        return

    await state.update_data(
        edit_user_id=user.user_id, edit_external_id=str(message.from_user.id)
    )
    draft = await fsm_draft_service.get_draft(user.user_id, EDIT_PROFILE_FLOW_TYPE)
    if draft is not None:
        await message.answer(DRAFT_QUESTION_TEXT, reply_markup=draft_choice_keyboard())
        await state.set_state(EditProfileStates.choosing_draft_restore)
        return
    if blogger is not None and advertiser is not None:
        await message.answer(
            "Выберите профиль для редактирования:",
            reply_markup=_edit_profile_type_keyboard(),
        )
        await state.set_state(EditProfileStates.choosing_profile_type)
        return
    if blogger is not None:
        await state.update_data(edit_profile_type="blogger")
        await message.answer(
            "Выберите раздел для редактирования:",
            reply_markup=_edit_field_keyboard("blogger"),
        )
        await state.set_state(EditProfileStates.choosing_field)
        return
    await state.update_data(edit_profile_type="advertiser")
    await message.answer(
        "Выберите раздел для редактирования:",
        reply_markup=_edit_field_keyboard("advertiser"),
    )
    await state.set_state(EditProfileStates.choosing_field)


@router.message(EditProfileStates.choosing_draft_restore)
async def edit_profile_draft_choice(
    message: Message,
    state: FSMContext,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Handle Continue or Start over when edit profile draft exists."""
    await handle_draft_choice(
        message,
        state,
        fsm_draft_service,
        flow_type=EDIT_PROFILE_FLOW_TYPE,
        user_id_key="edit_user_id",
        first_state=EditProfileStates.choosing_field,
        first_prompt="Выберите раздел для редактирования:",
        first_keyboard=_edit_field_keyboard("blogger"),
        session_expired_msg="Сессия истекла. Откройте «Мой профиль» снова.",
        draft_used_msg="Черновик уже использован. Выберите раздел.",
    )


@router.message(EditProfileStates.choosing_profile_type)
async def edit_profile_choose_type(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
) -> None:
    """Handle choice of blogger or advertiser profile to edit."""

    text = (message.text or "").strip()
    if text == MY_PROFILE_BUTTON_TEXT:
        await state.clear()
        await show_profile(message, profile_service, state)
        return
    if text == "Редактировать профиль блогера":
        await state.update_data(edit_profile_type="blogger")
        await message.answer(
            "Выберите раздел для редактирования:",
            reply_markup=_edit_field_keyboard("blogger"),
        )
        await state.set_state(EditProfileStates.choosing_field)
        return
    if text == "Редактировать профиль рекламодателя":
        await state.update_data(edit_profile_type="advertiser")
        await message.answer(
            "Выберите раздел для редактирования:",
            reply_markup=_edit_field_keyboard("advertiser"),
        )
        await state.set_state(EditProfileStates.choosing_field)
        return
    await message.answer(
        "Выберите один из вариантов на клавиатуре.",
        reply_markup=_edit_profile_type_keyboard(),
    )


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
    if text == MY_PROFILE_BUTTON_TEXT:
        await state.clear()
        await show_profile(message, profile_service, state)
        return

    data = await state.get_data()
    profile_type = data.get("edit_profile_type", "blogger")
    field_keys = (
        EDIT_FIELD_KEYS_ADVERTISER if profile_type == "advertiser" else EDIT_FIELD_KEYS
    )
    if text not in field_keys:
        await message.answer("Выберите один из разделов на клавиатуре.")
        return

    field_key = field_keys[text]
    await state.update_data(editing_field=field_key)

    prompts_blogger = {
        "nickname": "Введите новое имя:",
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
    prompts_advertiser = {
        "name": "Введите имя:",
        "phone": "Укажите номер телефона, по которому с вами можно связаться по заказу. Пример: +7 900 000-00-00",
        "brand": "Название вашего бренда / компании / бизнеса:",
        "site_link": "Ссылка на сайт, продукт или соцсети бренда:",
    }
    prompts = prompts_advertiser if profile_type == "advertiser" else prompts_blogger
    prompt = prompts.get(field_key, "Введите новое значение:")

    if field_key == "audience_gender":
        await message.answer(
            prompt,
            reply_markup=with_support_keyboard(
                keyboard=[
                    [KeyboardButton(text="👩 В основном женщины")],
                    [KeyboardButton(text="👨 В основном мужчины")],
                    [KeyboardButton(text="👥 Примерно поровну")],
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
                    [KeyboardButton(text=WORK_FORMAT_ADS_BUTTON_TEXT)],
                    [KeyboardButton(text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT)],
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
    advertiser_registration_service: AdvertiserRegistrationService,
    user_role_service: UserRoleService,
) -> None:
    """Validate and save new field value, then show profile."""

    data = await state.get_data()
    field_key = data.get("editing_field")
    user_id = parse_user_id_from_state(data, key="edit_user_id")
    external_id_raw = data.get("edit_external_id")
    profile_type = data.get("edit_profile_type", "blogger")
    if not field_key or user_id is None or not external_id_raw:
        await state.clear()
        await message.answer("Сессия истекла. Откройте «Мой профиль» снова.")
        return
    external_id = str(external_id_raw)

    if profile_type == "advertiser":
        advertiser = await profile_service.get_advertiser_profile(user_id)
        if advertiser is None:
            await state.clear()
            await message.answer("Профиль рекламодателя не найден.")
            return
        text = (message.text or "").strip()
        if field_key == "name":
            if not text:
                await message.answer("Имя не может быть пустым.")
                return
            await user_role_service.set_user(
                external_id=external_id,
                messenger_type=MessengerType.TELEGRAM,
                username=text,
            )
            await state.clear()
            await message.answer(
                "Профиль обновлён.",
                reply_markup=advertiser_menu_keyboard(),
            )
            await show_profile(message, profile_service, state)
            return
        elif field_key == "phone":
            if not text:
                await message.answer("Номер телефона не может быть пустым.")
                return
            updated = await advertiser_registration_service.update_advertiser_profile(
                user_id, phone=text
            )
        elif field_key == "brand":
            if not text:
                await message.answer("Название бренда не может быть пустым.")
                return
            updated = await advertiser_registration_service.update_advertiser_profile(
                user_id, brand=text
            )
        elif field_key == "site_link":
            updated = await advertiser_registration_service.update_advertiser_profile(
                user_id, site_link=text or None
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
            reply_markup=advertiser_menu_keyboard(),
        )
        await show_profile(message, profile_service, state)
        return

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
        await show_profile(message, profile_service, state)
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
        updated_blogger = await blogger_registration_service.update_blogger_profile(
            user_id, instagram_url=text
        )
    elif field_key == "city":
        if not text:
            await message.answer("Город не может быть пустым.")
            return
        updated_blogger = await blogger_registration_service.update_blogger_profile(
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
        updated_blogger = await blogger_registration_service.update_blogger_profile(
            user_id, topics={"selected": topics}
        )
    elif field_key == "audience_gender":
        key = text[2:].lower()
        gender_map = {
            "в основном женщины": AudienceGender.FEMALE,
            "в основном мужчины": AudienceGender.MALE,
            "примерно поровну": AudienceGender.ALL,
        }
        if key not in gender_map:
            await message.answer("Выберите одну из кнопок.")
            return
        updated_blogger = await blogger_registration_service.update_blogger_profile(
            user_id, audience_gender=gender_map[key]
        )
    elif field_key == "audience_age":
        if text not in _AGE_BUTTONS:
            await message.answer("Выберите одну из кнопок возраста.")
            return
        min_age, max_age = _AGE_BUTTONS[text]
        updated_blogger = await blogger_registration_service.update_blogger_profile(
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
        updated_blogger = await blogger_registration_service.update_blogger_profile(
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
        updated_blogger = await blogger_registration_service.update_blogger_profile(
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
        updated_blogger = await blogger_registration_service.update_blogger_profile(
            user_id, barter=barter
        )
    elif field_key == "work_format":
        if text == WORK_FORMAT_ADS_BUTTON_TEXT:
            wf = WorkFormat.ADS_IN_ACCOUNT
        elif text == WORK_FORMAT_UGC_ONLY_BUTTON_TEXT:
            wf = WorkFormat.UGC_ONLY
        else:
            await message.answer("Выберите одну из кнопок.")
            return
        updated_blogger = await blogger_registration_service.update_blogger_profile(
            user_id, work_format=wf
        )
    else:
        await state.clear()
        await message.answer("Неизвестное поле.")
        return

    if updated_blogger is None:
        await state.clear()
        await message.answer("Не удалось обновить профиль.")
        return

    await state.clear()
    await message.answer(
        "Профиль обновлён.",
        reply_markup=blogger_profile_view_keyboard(updated_blogger.confirmed),
    )
    await show_profile(message, profile_service, state)
