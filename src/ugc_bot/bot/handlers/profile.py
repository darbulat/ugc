"""Profile view and edit handlers."""

import logging
import re
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from ugc_bot.application.messenger.context import MessageContext
from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    EDIT_PROFILE_BUTTON_TEXT,
    MY_PROFILE_BUTTON_TEXT,
    WORK_FORMAT_ADS_BUTTON_TEXT,
    WORK_FORMAT_UGC_ONLY_BUTTON_TEXT,
    advertiser_menu_keyboard,
    blogger_profile_view_keyboard,
    flow_keyboard,
    flow_keyboard_remove,
)
from ugc_bot.bot.handlers.utils import (
    parse_user_id_from_state,
    resolve_messenger_dependencies,
)
from ugc_bot.bot.validators import (
    normalize_instagram_url,
    validate_audience_geo,
    validate_brand,
    validate_city,
    validate_company_activity,
    validate_name,
    validate_nickname,
    validate_phone,
    validate_price,
    validate_site_link,
    validate_topics,
)
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)

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
                f"   Целевая аудитория: {gender_label}, "
                f"{blogger.audience_age_min}–{blogger.audience_age_max} лет",
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
        if advertiser.city:
            adv_lines.append(f"   Город: {advertiser.city}")
        if advertiser.company_activity:
            adv_lines.append(f"   Деятельность: {advertiser.company_activity}")
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
    ("Город", "city"),
    ("Бренд", "brand"),
    ("Деятельность компании", "company_activity"),
    ("Ссылка на сайт", "site_link"),
]
EDIT_FIELD_LABELS_ADVERTISER = [label for label, _ in _EDIT_FIELDS_ADVERTISER]
EDIT_FIELD_KEYS_ADVERTISER = {
    label: key for label, key in _EDIT_FIELDS_ADVERTISER
}

_AGE_BUTTONS: dict[str, tuple[int, int]] = {
    "до 18": (1, 17),
    "18–24": (18, 24),
    "25–34": (25, 34),
    "35–44": (35, 44),
    "45+": (45, 99),
}


EDIT_PROFILE_FLOW_TYPE = "edit_profile"


async def _adv_update_contact(
    text: str,
    user_id: UUID,
    message: MessageContext,
    advertiser_registration_service: AdvertiserRegistrationService,
) -> AdvertiserProfile | None:
    """Update phone. Returns profile or None."""
    err = validate_phone(text)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await advertiser_registration_service.update_advertiser_profile(
        user_id, phone=text
    )


async def _adv_update_brand(
    text: str,
    user_id: UUID,
    message: MessageContext,
    advertiser_registration_service: AdvertiserRegistrationService,
) -> AdvertiserProfile | None:
    """Update brand. Returns profile or None."""
    err = validate_brand(text)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await advertiser_registration_service.update_advertiser_profile(
        user_id, brand=text
    )


async def _adv_update_site_link(
    text: str,
    user_id: UUID,
    message: MessageContext,
    advertiser_registration_service: AdvertiserRegistrationService,
) -> AdvertiserProfile | None:
    """Update site_link. Returns profile or None."""
    err = validate_site_link(text or None)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await advertiser_registration_service.update_advertiser_profile(
        user_id, site_link=text or None
    )


async def _adv_update_city(
    text: str,
    user_id: UUID,
    message: MessageContext,
    advertiser_registration_service: AdvertiserRegistrationService,
) -> AdvertiserProfile | None:
    """Update city. Returns profile or None."""
    err = validate_city(text or None, required=False)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await advertiser_registration_service.update_advertiser_profile(
        user_id, city=text or None
    )


async def _adv_update_company_activity(
    text: str,
    user_id: UUID,
    message: MessageContext,
    advertiser_registration_service: AdvertiserRegistrationService,
) -> AdvertiserProfile | None:
    """Update company_activity. Returns profile or None."""
    err = validate_company_activity(text or None)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await advertiser_registration_service.update_advertiser_profile(
        user_id, company_activity=text or None
    )


async def _update_advertiser_field(
    message: MessageContext,
    state: FSMContext,
    field_key: str,
    text: str,
    user_id: UUID,
    external_id: str,
    advertiser: AdvertiserProfile,
    profile_service: ProfileService,
    advertiser_registration_service: AdvertiserRegistrationService,
    user_role_service: UserRoleService,
) -> bool:
    """Validate and update advertiser field. Returns True on success."""
    if field_key == "name":
        err = validate_name(text)
        if err is not None:
            await message.answer(err, reply_markup=flow_keyboard_remove())
            return False
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
        return True

    updaters = {
        "phone": _adv_update_contact,
        "brand": _adv_update_brand,
        "site_link": _adv_update_site_link,
        "city": _adv_update_city,
        "company_activity": _adv_update_company_activity,
    }
    updater = updaters.get(field_key)
    if updater is None:
        await state.clear()
        await message.answer("Неизвестное поле.")
        return False
    updated = await updater(
        text, user_id, message, advertiser_registration_service
    )
    if updated is None:
        await state.clear()
        await message.answer("Не удалось обновить профиль.")
        return False
    await state.clear()
    await message.answer(
        "Профиль обновлён.",
        reply_markup=advertiser_menu_keyboard(),
    )
    await show_profile(message, profile_service, state)
    return True


async def _blog_update_instagram(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
) -> BloggerProfile | None:
    """Update instagram_url. Returns profile or None."""
    if not text or "instagram.com/" not in text.lower():
        await message.answer(
            "Неверный формат ссылки. Пример: instagram.com/name"
        )
        return None
    text = normalize_instagram_url(text)
    if not _INSTAGRAM_URL_REGEX.match(text):
        await message.answer("Неверный формат ссылки Instagram.")
        return None
    existing = await blogger_registration_service.get_profile_by_instagram_url(
        text
    )
    if existing is not None and existing.user_id != user_id:
        await message.answer(
            "Этот Instagram уже зарегистрирован. Используйте другой."
        )
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, instagram_url=text
    )


async def _blog_update_city(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
) -> BloggerProfile | None:
    """Update city. Returns profile or None."""
    err = validate_city(text, required=True)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, city=text
    )


async def _blog_update_topics(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
) -> BloggerProfile | None:
    """Update topics. Returns profile or None."""
    topics = [t.strip().lower() for t in text.split(",") if t.strip()]
    err = validate_topics(topics)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, topics={"selected": topics}
    )


async def _blog_update_audience_gender(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
) -> BloggerProfile | None:
    """Update audience_gender. Returns profile or None."""
    key = text[2:].lower()
    gender_map = {
        "в основном женщины": AudienceGender.FEMALE,
        "в основном мужчины": AudienceGender.MALE,
        "примерно поровну": AudienceGender.ALL,
    }
    if key not in gender_map:
        await message.answer("Выберите одну из кнопок.")
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, audience_gender=gender_map[key]
    )


async def _blog_update_audience_age(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
) -> BloggerProfile | None:
    """Update audience_age. Returns profile or None."""
    if text not in _AGE_BUTTONS:
        await message.answer("Выберите одну из кнопок возраста.")
        return None
    min_age, max_age = _AGE_BUTTONS[text]
    return await blogger_registration_service.update_blogger_profile(
        user_id, audience_age_min=min_age, audience_age_max=max_age
    )


async def _blog_update_audience_geo(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
) -> BloggerProfile | None:
    """Update audience_geo. Returns profile or None."""
    err = validate_audience_geo(text)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    cities = [c.strip() for c in text.split(",") if c.strip()]
    if len(cities) > 3:
        await message.answer(
            "Укажите не более 3 городов.",
            reply_markup=flow_keyboard_remove(),
        )
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, audience_geo=text
    )


async def _blog_update_price(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    max_order_price: float,
) -> BloggerProfile | None:
    """Update price. Returns profile or None."""
    try:
        price = float(text.replace(",", "."))
    except ValueError:
        await message.answer("Введите число, например 1000.")
        return None
    err = validate_price(price, max_order_price)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, price=price
    )


async def _blog_update_barter(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
) -> BloggerProfile | None:
    """Update barter. Returns profile or None."""
    if text.lower() == "да":
        barter = True
    elif text.lower() == "нет":
        barter = False
    else:
        await message.answer("Выберите Да или Нет.")
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, barter=barter
    )


async def _blog_update_work_format(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
) -> BloggerProfile | None:
    """Update work_format. Returns profile or None."""
    if text == WORK_FORMAT_ADS_BUTTON_TEXT:
        wf = WorkFormat.ADS_IN_ACCOUNT
    elif text == WORK_FORMAT_UGC_ONLY_BUTTON_TEXT:
        wf = WorkFormat.UGC_ONLY
    else:
        await message.answer("Выберите одну из кнопок.")
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, work_format=wf
    )


async def _update_blogger_field(
    message: MessageContext,
    state: FSMContext,
    field_key: str,
    text: str,
    user_id: UUID,
    external_id: str,
    blogger: BloggerProfile,
    profile_service: ProfileService,
    blogger_registration_service: BloggerRegistrationService,
    user_role_service: UserRoleService,
    max_order_price: float,
) -> bool:
    """Validate and update blogger field. Returns True on success."""
    if field_key == "nickname":
        err = validate_nickname(text)
        if err is not None:
            await message.answer(err, reply_markup=flow_keyboard_remove())
            return False
        await user_role_service.set_user(
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM,
            username=text,
        )
        await state.clear()
        await message.answer(
            "Имя обновлено.",
            reply_markup=blogger_profile_view_keyboard(blogger.confirmed),
        )
        await show_profile(message, profile_service, state)
        return True

    updaters = {
        "instagram_url": _blog_update_instagram,
        "city": _blog_update_city,
        "topics": _blog_update_topics,
        "audience_gender": _blog_update_audience_gender,
        "audience_age": _blog_update_audience_age,
        "audience_geo": _blog_update_audience_geo,
        "price": lambda t, u, m, s: _blog_update_price(
            t, u, m, s, max_order_price
        ),
        "barter": _blog_update_barter,
        "work_format": _blog_update_work_format,
    }
    updater = updaters.get(field_key)
    if updater is None:
        await state.clear()
        await message.answer("Неизвестное поле.")
        return False
    updated_blogger = await updater(
        text, user_id, message, blogger_registration_service
    )
    if updated_blogger is None:
        await state.clear()
        await message.answer("Не удалось обновить профиль.")
        return False
    await state.clear()
    await message.answer(
        "Профиль обновлён.",
        reply_markup=blogger_profile_view_keyboard(updated_blogger.confirmed),
    )
    await show_profile(message, profile_service, state)
    return True


class EditProfileStates(StatesGroup):
    """States for editing blogger or advertiser profile."""

    choosing_profile_type = State()
    choosing_field = State()
    entering_value = State()


@router.message(Command("profile"))
@router.message(lambda msg: (msg.text or "").strip() == MY_PROFILE_BUTTON_TEXT)
async def show_profile(
    message: Message,
    profile_service: ProfileService,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Show current user's profile."""
    if isinstance(message, MessageContext):
        message_ctx = message
    else:
        messenger_client, event_adapter = resolve_messenger_dependencies(
            message, messenger_client, event_adapter
        )
        incoming = event_adapter.from_message(message)
        message_ctx = MessageContext(incoming, messenger_client)
    await state.clear()

    if message_ctx.from_user is None or not message_ctx.from_user.id:
        return

    user = await profile_service.get_user_by_external(
        external_id=str(message_ctx.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await message_ctx.answer(
            "Профиль не найден. Выберите роль через /role."
        )
        return

    blogger = await profile_service.get_blogger_profile(user.user_id)
    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    text = _format_profile_text(user, blogger, advertiser)

    reply_markup = None
    if blogger is not None:
        reply_markup = blogger_profile_view_keyboard(
            confirmed=blogger.confirmed
        )
    elif advertiser is not None:
        reply_markup = advertiser_menu_keyboard()

    await message_ctx.answer(text, reply_markup=reply_markup)


def _edit_field_keyboard(profile_type: str = "blogger") -> Keyboard:
    """Keyboard with profile fields for editing (two per row)."""

    labels = (
        EDIT_FIELD_LABELS_ADVERTISER
        if profile_type == "advertiser"
        else EDIT_FIELD_LABELS
    )
    rows: list[list[Button]] = []
    for i in range(0, len(labels), 2):
        row = [Button(text=labels[i])]
        if i + 1 < len(labels):
            row.append(Button(text=labels[i + 1]))
        rows.append(row)
    rows.append([Button(text=MY_PROFILE_BUTTON_TEXT)])
    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=rows,
        resize=True,
        one_time=False,
    )


def _edit_profile_type_keyboard() -> Keyboard:
    """Keyboard to choose blogger or advertiser profile to edit."""
    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text="Редактировать профиль блогера")],
            [Button(text="Редактировать профиль рекламодателя")],
            [Button(text=MY_PROFILE_BUTTON_TEXT)],
        ],
        resize=True,
        one_time=False,
    )


@router.message(
    lambda msg: (msg.text or "").strip() == EDIT_PROFILE_BUTTON_TEXT
)
async def edit_profile_start(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Show field selection for profile edit."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)

    if message_ctx.from_user is None or not message_ctx.from_user.id:
        return

    user = await profile_service.get_user_by_external(
        external_id=str(message_ctx.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await message_ctx.answer(
            "Профиль не найден. Выберите роль через /role."
        )
        return

    blogger = await profile_service.get_blogger_profile(user.user_id)
    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if blogger is None and advertiser is None:
        await message_ctx.answer("Профиль не заполнен.")
        return

    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id=str(message_ctx.from_user.id),
    )
    if blogger is not None and advertiser is not None:
        await message_ctx.answer(
            "Выберите профиль для редактирования:",
            reply_markup=_edit_profile_type_keyboard(),
        )
        await state.set_state(EditProfileStates.choosing_profile_type)
        return
    if blogger is not None:
        await state.update_data(edit_profile_type="blogger")
        await message_ctx.answer(
            "Выберите раздел для редактирования:",
            reply_markup=_edit_field_keyboard("blogger"),
        )
        await state.set_state(EditProfileStates.choosing_field)
        return
    await state.update_data(edit_profile_type="advertiser")
    await message_ctx.answer(
        "Выберите раздел для редактирования:",
        reply_markup=_edit_field_keyboard("advertiser"),
    )
    await state.set_state(EditProfileStates.choosing_field)


@router.message(EditProfileStates.choosing_profile_type)
async def edit_profile_choose_type(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle choice of blogger or advertiser profile to edit."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)
    text = (message_ctx.text or "").strip()
    if text == MY_PROFILE_BUTTON_TEXT:
        await state.clear()
        await show_profile(
            message=message_ctx,
            profile_service=profile_service,
            state=state,
            messenger_client=messenger_client,
            event_adapter=event_adapter,
        )
        return
    if text == "Редактировать профиль блогера":
        await state.update_data(edit_profile_type="blogger")
        await message_ctx.answer(
            "Выберите раздел для редактирования:",
            reply_markup=_edit_field_keyboard("blogger"),
        )
        await state.set_state(EditProfileStates.choosing_field)
        return
    if text == "Редактировать профиль рекламодателя":
        await state.update_data(edit_profile_type="advertiser")
        await message_ctx.answer(
            "Выберите раздел для редактирования:",
            reply_markup=_edit_field_keyboard("advertiser"),
        )
        await state.set_state(EditProfileStates.choosing_field)
        return
    await message_ctx.answer(
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
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle field choice and ask for new value."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)
    text = (message_ctx.text or "").strip()
    if text == MY_PROFILE_BUTTON_TEXT:
        await state.clear()
        await show_profile(
            message=message_ctx,
            profile_service=profile_service,
            state=state,
            messenger_client=messenger_client,
            event_adapter=event_adapter,
        )
        return

    data = await state.get_data()
    profile_type = data.get("edit_profile_type", "blogger")
    field_keys = (
        EDIT_FIELD_KEYS_ADVERTISER
        if profile_type == "advertiser"
        else EDIT_FIELD_KEYS
    )
    if text not in field_keys:
        await message_ctx.answer("Выберите один из разделов на клавиатуре.")
        return

    field_key = field_keys[text]
    await state.update_data(editing_field=field_key)

    prompts_blogger = {
        "nickname": "Введите новое имя:",
        "instagram_url": "Прикрепите ссылку instagram.com/name:",
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
        "phone": "Укажите номер телефона для связи. Пример: 89001110777",
        "brand": "Название вашего бренда / компании / бизнеса:",
        "site_link": "Ссылка на сайт, продукт или соцсети бренда:",
    }
    prompts = (
        prompts_advertiser if profile_type == "advertiser" else prompts_blogger
    )
    prompt = prompts.get(field_key, "Введите новое значение:")

    if field_key == "audience_gender":
        await message_ctx.answer(
            prompt,
            reply_markup=flow_keyboard(
                keyboard=[
                    [Button(text="👩 В основном женщины")],
                    [Button(text="👨 В основном мужчины")],
                    [Button(text="👥 Примерно поровну")],
                ],
            ),
        )
    elif field_key == "audience_age":
        await message_ctx.answer(
            prompt,
            reply_markup=flow_keyboard(
                keyboard=[
                    [Button(text="до 18")],
                    [Button(text="18–24")],
                    [Button(text="25–34")],
                    [Button(text="35–44")],
                    [Button(text="45+")],
                ],
            ),
        )
    elif field_key == "barter":
        await message_ctx.answer(
            prompt,
            reply_markup=flow_keyboard(
                keyboard=[
                    [Button(text="Да")],
                    [Button(text="Нет")],
                ],
            ),
        )
    elif field_key == "work_format":
        await message_ctx.answer(
            prompt,
            reply_markup=flow_keyboard(
                keyboard=[
                    [Button(text=WORK_FORMAT_ADS_BUTTON_TEXT)],
                    [Button(text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT)],
                ],
            ),
        )
    else:
        await message_ctx.answer(prompt, reply_markup=flow_keyboard_remove())

    await state.set_state(EditProfileStates.entering_value)


@router.message(EditProfileStates.entering_value)
async def edit_profile_enter_value(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    blogger_registration_service: BloggerRegistrationService,
    advertiser_registration_service: AdvertiserRegistrationService,
    user_role_service: UserRoleService,
    max_order_price: float,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Validate and save new field value, then show profile."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)
    data = await state.get_data()
    field_key = data.get("editing_field")
    user_id = parse_user_id_from_state(data, key="edit_user_id")
    external_id_raw = data.get("edit_external_id")
    profile_type = data.get("edit_profile_type", "blogger")
    if not field_key or user_id is None or not external_id_raw:
        await state.clear()
        await message_ctx.answer(
            "Сессия истекла. Откройте «Мой профиль» снова."
        )
        return
    external_id = str(external_id_raw)
    text = (message_ctx.text or "").strip()

    if profile_type == "advertiser":
        advertiser = await profile_service.get_advertiser_profile(user_id)
        if advertiser is None:
            await state.clear()
            await message_ctx.answer("Профиль рекламодателя не найден.")
            return
        await _update_advertiser_field(
            message_ctx,
            state,
            field_key,
            text,
            user_id,
            external_id,
            advertiser,
            profile_service,
            advertiser_registration_service,
            user_role_service,
        )
        return

    blogger = await profile_service.get_blogger_profile(user_id)
    if blogger is None:
        await state.clear()
        await message_ctx.answer("Профиль не найден.")
        return
    await _update_blogger_field(
        message_ctx,
        state,
        field_key,
        text,
        user_id,
        external_id,
        blogger,
        profile_service,
        blogger_registration_service,
        user_role_service,
        max_order_price,
    )
