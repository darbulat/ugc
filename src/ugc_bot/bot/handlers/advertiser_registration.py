"""Advertiser registration flow handlers."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed,
    handle_draft_choice,
    parse_user_id_from_state,
)
from ugc_bot.bot.handlers.keyboards import (
    ADVERTISER_START_BUTTON_TEXT,
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    DRAFT_QUESTION_TEXT,
    advertiser_menu_keyboard,
    advertiser_start_keyboard,
    draft_choice_keyboard,
    support_keyboard,
)
from ugc_bot.bot.handlers.start import ADVERTISER_LABEL
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import MessengerType


router = Router()
logger = logging.getLogger(__name__)


ADVERTISER_FLOW_TYPE = "advertiser_registration"
ADVERTISER_CHOOSE_ACTION_TEXT = "Выберите действие:"
ADVERTISER_INTRO_TEXT = (
    "Вы выбрали роль «Мне нужны UGC‑креаторы».\n"
    "Давайте создадим профиль, чтобы вы могли размещать заказы."
)


@router.message(Command("advertiser"))
@router.message(lambda msg: (msg.text or "").strip() == ADVERTISER_LABEL)
async def choose_advertiser_role(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state: FSMContext,
) -> None:
    """Handle 'Мне нужны UGC‑креаторы': persist role and show menu or registration prompt."""

    if message.from_user is None:
        return
    await state.clear()
    external_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name or "user"

    await user_role_service.set_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
        role_chosen=True,
        telegram_username=message.from_user.username,
    )

    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
    )
    advertiser_profile = (
        await profile_service.get_advertiser_profile(user.user_id) if user else None
    )
    if advertiser_profile is not None:
        await message.answer(
            ADVERTISER_CHOOSE_ACTION_TEXT,
            reply_markup=advertiser_menu_keyboard(),
        )
    else:
        await message.answer(
            ADVERTISER_INTRO_TEXT,
            reply_markup=advertiser_start_keyboard(),
        )


class AdvertiserRegistrationStates(StatesGroup):
    """States for advertiser registration."""

    choosing_draft_restore = State()
    name = State()
    phone = State()
    brand = State()
    site_link = State()
    agreements = State()


async def _ask_name(message: Message, state: FSMContext) -> None:
    """Send name prompt and set state to name."""
    await message.answer(
        "Как вас зовут?",
        reply_markup=support_keyboard(),
    )
    await state.set_state(AdvertiserRegistrationStates.name)


@router.message(lambda msg: (msg.text or "").strip() == ADVERTISER_START_BUTTON_TEXT)
async def handle_advertiser_start(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Handle 'Начать' after advertiser role: show menu if profile exists, else start registration."""

    user = await get_user_and_ensure_allowed(
        message,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Начните с /start.",
        blocked_msg="Заблокированные пользователи не могут регистрироваться.",
        pause_msg="Пользователи на паузе не могут регистрироваться.",
    )
    if user is None:
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is not None:
        await message.answer(
            "Выберите действие:",
            reply_markup=advertiser_menu_keyboard(),
        )
        return

    await state.update_data(user_id=user.user_id)
    draft = await fsm_draft_service.get_draft(user.user_id, ADVERTISER_FLOW_TYPE)
    if draft is not None:
        await message.answer(DRAFT_QUESTION_TEXT, reply_markup=draft_choice_keyboard())
        await state.set_state(AdvertiserRegistrationStates.choosing_draft_restore)
        return
    await _ask_name(message, state)


@router.message(AdvertiserRegistrationStates.choosing_draft_restore)
async def advertiser_draft_choice(
    message: Message,
    state: FSMContext,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Handle Continue or Start over when draft exists."""
    await handle_draft_choice(
        message,
        state,
        fsm_draft_service,
        flow_type=ADVERTISER_FLOW_TYPE,
        user_id_key="user_id",
        first_state=AdvertiserRegistrationStates.name,
        first_prompt="Как вас зовут?",
        first_keyboard=support_keyboard(),
        session_expired_msg="Сессия истекла. Начните снова.",
    )


@router.message(AdvertiserRegistrationStates.name)
async def handle_name(message: Message, state: FSMContext) -> None:
    """Store name and ask for phone."""

    name = (message.text or "").strip()
    if not name:
        await message.answer(
            "Имя не может быть пустым. Введите снова:",
            reply_markup=support_keyboard(),
        )
        return

    await state.update_data(name=name)
    await message.answer(
        "Укажите номер телефона, по которому с вами можно связаться по заказу.\n"
        "Пример: +7 900 000-00-00",
        reply_markup=support_keyboard(),
    )
    await state.set_state(AdvertiserRegistrationStates.phone)


@router.message(AdvertiserRegistrationStates.phone)
async def handle_phone(message: Message, state: FSMContext) -> None:
    """Store phone and ask for brand."""

    phone = (message.text or "").strip()
    if not phone:
        await message.answer(
            "Номер телефона не может быть пустым. Введите снова:",
            reply_markup=support_keyboard(),
        )
        return

    await state.update_data(phone=phone)
    await message.answer(
        "Название вашего бренда / компании / бизнеса:",
        reply_markup=support_keyboard(),
    )
    await state.set_state(AdvertiserRegistrationStates.brand)


@router.message(AdvertiserRegistrationStates.brand)
async def handle_brand(message: Message, state: FSMContext) -> None:
    """Store brand and ask for site link."""

    brand = (message.text or "").strip()
    if not brand:
        await message.answer(
            "Название бренда не может быть пустым. Введите снова:",
            reply_markup=support_keyboard(),
        )
        return

    await state.update_data(brand=brand)
    await message.answer(
        "Ссылка на сайт, продукт или соцсети бренда:",
        reply_markup=support_keyboard(),
    )
    await state.set_state(AdvertiserRegistrationStates.site_link)


def _agreements_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard with single 'Confirm agreement' button."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CONFIRM_AGREEMENT_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _format_agreements_message(config: AppConfig) -> str:
    """Build agreements text with clickable document links (HTML)."""
    parts = [
        "Профиль создан. Остался последний шаг — ознакомьтесь с документами "
        "и подтвердите согласие.",
        "",
    ]
    if config.docs.docs_offer_url:
        parts.append(f'<a href="{config.docs.docs_offer_url}">Оферта</a>')
    if config.docs.docs_privacy_url:
        parts.append(
            f'<a href="{config.docs.docs_privacy_url}">Политика конфиденциальности</a>'
        )
    if config.docs.docs_consent_url:
        parts.append(
            f'<a href="{config.docs.docs_consent_url}">Согласие на обработку ПД</a>'
        )
    if len(parts) == 2:
        parts.append("Подтвердите согласие с документами платформы.")
    return "\n".join(parts)


@router.message(AdvertiserRegistrationStates.site_link)
async def handle_site_link(
    message: Message,
    state: FSMContext,
    config: AppConfig,
) -> None:
    """Store site_link and show agreements step."""

    site_link = (message.text or "").strip() or None
    await state.update_data(site_link=site_link)

    text = _format_agreements_message(config)
    await message.answer(
        text,
        reply_markup=_agreements_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdvertiserRegistrationStates.agreements)


@router.message(AdvertiserRegistrationStates.agreements)
async def handle_agreements_confirm(
    message: Message,
    state: FSMContext,
    advertiser_registration_service: AdvertiserRegistrationService,
) -> None:
    """On 'Confirm agreement' create profile and show success."""

    if (message.text or "").strip() != CONFIRM_AGREEMENT_BUTTON_TEXT:
        await message.answer(
            "Нажмите кнопку «Подтвердить согласие», чтобы завершить регистрацию.",
            reply_markup=_agreements_keyboard(),
        )
        return

    data = await state.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await message.answer("Сессия истекла. Начните заново.")
        await state.clear()
        return
    name = data["name"]
    phone = data["phone"]
    brand = data["brand"]
    site_link = data.get("site_link")

    await advertiser_registration_service.register_advertiser(
        user_id=user_id,
        name=name,
        phone=phone,
        brand=brand,
        site_link=site_link,
    )

    await state.clear()
    await message.answer(
        "Теперь вы можете разместить заказ и найти UGC-креаторов под вашу задачу.",
        reply_markup=advertiser_menu_keyboard(),
    )
