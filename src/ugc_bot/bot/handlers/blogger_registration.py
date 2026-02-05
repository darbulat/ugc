"""Blogger registration flow handlers."""

import logging
import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.application.services.order_service import MAX_ORDER_PRICE
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    CREATE_PROFILE_BUTTON_TEXT,
    DRAFT_QUESTION_TEXT,
    WORK_FORMAT_ADS_BUTTON_TEXT,
    WORK_FORMAT_UGC_ONLY_BUTTON_TEXT,
    blogger_after_registration_keyboard,
    creator_filled_profile_keyboard,
    creator_start_keyboard,
    draft_choice_keyboard,
    support_keyboard,
    with_support_keyboard,
)
from ugc_bot.bot.handlers.start import CREATOR_LABEL
from ugc_bot.bot.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
    handle_draft_choice,
    handle_role_choice,
    parse_user_id_from_state,
)
from ugc_bot.bot.validators import (
    validate_audience_geo,
    validate_city,
    validate_nickname,
    validate_price,
    validate_topics,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import AudienceGender, MessengerType, WorkFormat

router = Router()
logger = logging.getLogger(__name__)

CREATOR_CHOOSE_ACTION_TEXT = "Выберите действие:"
CREATOR_INTRO_NOT_REGISTERED = (
    "Ты — UGC‑креатор.\n"
    "После регистрации бренды смогут находить тебя и отправлять предложения."
)

_INSTAGRAM_URL_REGEX = re.compile(
    r"^(https?://)?(www\.)?instagram\.com/[A-Za-z0-9._]+/?$"
)


class BloggerRegistrationStates(StatesGroup):
    """States for blogger registration."""

    choosing_draft_restore = State()
    name = State()
    instagram = State()
    city = State()
    topics = State()
    audience_gender = State()
    audience_age = State()
    audience_geo = State()
    price = State()
    barter = State()
    work_format = State()
    agreements = State()


BLOGGER_FLOW_TYPE = "blogger_registration"


@router.message(Command("creator"))
@router.message(lambda msg: (msg.text or "").strip() == CREATOR_LABEL)
async def choose_creator_role(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state: FSMContext,
) -> None:
    """Handle 'Я креатор': persist role and show menu or registration prompt."""

    await handle_role_choice(
        message,
        user_role_service,
        state,
        profile_getter=profile_service.get_blogger_profile,
        choose_action_text=CREATOR_CHOOSE_ACTION_TEXT,
        intro_text=CREATOR_INTRO_NOT_REGISTERED,
        menu_keyboard=creator_filled_profile_keyboard,
        start_keyboard=creator_start_keyboard,
    )


async def _start_registration_flow(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Start blogger registration: check draft, then first step (name)."""

    user = await get_user_and_ensure_allowed(
        message,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Начните с /start.",
        blocked_msg="Заблокированные пользователи не могут регистрироваться.",
        pause_msg="Пользователи на паузе не могут регистрироваться.",
    )
    if user is None:
        return

    await state.update_data(user_id=user.user_id, external_id=user.external_id)
    draft = await fsm_draft_service.get_draft(user.user_id, BLOGGER_FLOW_TYPE)
    if draft is not None:
        await message.answer(
            DRAFT_QUESTION_TEXT, reply_markup=draft_choice_keyboard()
        )
        await state.set_state(BloggerRegistrationStates.choosing_draft_restore)
        return

    if user.username and len(user.username.strip()) >= 2:
        await state.update_data(nickname=user.username)
        await message.answer(
            "Прикрепите ссылку на инстаграмм в формате instagram.com/name",
            reply_markup=support_keyboard(),
        )
        await state.set_state(BloggerRegistrationStates.instagram)
    else:
        await message.answer(
            "Введите ваше имя:",
            reply_markup=support_keyboard(),
        )
        await state.set_state(BloggerRegistrationStates.name)


@router.message(
    lambda msg: (msg.text or "").strip() == CREATE_PROFILE_BUTTON_TEXT
)
async def start_registration_button(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Start blogger registration flow via Create profile button."""

    await _start_registration_flow(
        message, state, user_role_service, fsm_draft_service
    )


@router.message(BloggerRegistrationStates.choosing_draft_restore)
async def blogger_draft_choice(
    message: Message,
    state: FSMContext,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Handle Continue or Start over when draft exists."""
    await handle_draft_choice(
        message,
        state,
        fsm_draft_service,
        flow_type=BLOGGER_FLOW_TYPE,
        user_id_key="user_id",
        first_state=BloggerRegistrationStates.name,
        first_prompt="Введите ваше имя:",
        first_keyboard=support_keyboard(),
        session_expired_msg="Сессия истекла. Начните с «Создать профиль».",
    )


@router.message(BloggerRegistrationStates.name)
async def handle_name(message: Message, state: FSMContext) -> None:
    """Store nickname."""

    nickname = (message.text or "").strip()
    err = validate_nickname(nickname)
    if err is not None:
        await message.answer(err, reply_markup=support_keyboard())
        return

    await state.update_data(nickname=nickname)
    await message.answer(
        "Прикрепите ссылку на инстаграмм в формате instagram.com/name",
        reply_markup=support_keyboard(),
    )
    await state.set_state(BloggerRegistrationStates.instagram)


@router.message(BloggerRegistrationStates.instagram)
async def handle_instagram(
    message: Message,
    state: FSMContext,
    blogger_registration_service: BloggerRegistrationService,
) -> None:
    """Store Instagram URL."""

    instagram_url = (message.text or "").strip()
    if not instagram_url:
        await message.answer("Ссылка не может быть пустой. Введите снова:")
        return
    if "instagram.com/" not in instagram_url.lower():
        await message.answer(
            "Неверный формат ссылки. Прикрепите instagram.com/name"
        )
        return
    if not _INSTAGRAM_URL_REGEX.match(instagram_url):
        await message.answer(
            "Неверный формат ссылки Instagram. Пример: https://instagram.com/name"
        )
        return

    # Check if Instagram URL is already taken
    existing_profile = (
        await blogger_registration_service.get_profile_by_instagram_url(
            instagram_url
        )
    )
    if existing_profile is not None:
        await message.answer(
            "Этот Instagram аккаунт уже зарегистрирован. "
            "Пожалуйста, используйте другой аккаунт или обратитесь в поддержку."
        )
        return

    await state.update_data(instagram_url=instagram_url)
    await message.answer(
        "Из какого вы города?\nПример: Казань / Москва / Санкт‑Петербург",
        reply_markup=support_keyboard(),
    )
    await state.set_state(BloggerRegistrationStates.city)


@router.message(BloggerRegistrationStates.city)
async def handle_city(message: Message, state: FSMContext) -> None:
    """Store creator city."""

    city = (message.text or "").strip()
    err = validate_city(city, required=True)
    if err is not None:
        await message.answer(err, reply_markup=support_keyboard())
        return

    await state.update_data(city=city)
    topics_text = (
        "О чём ваш контент?\n"
        "Напишите 1–3 тематики через запятую: бизнес, инвестиции, фитнес, "
        "питание, бьюти, уход за кожей, путешествия, еда, рестораны, мода, "
        "стиль, дети, семья, технологии, гаджеты, лайфстайл, другое"
    )
    await message.answer(topics_text, reply_markup=support_keyboard())
    await state.set_state(BloggerRegistrationStates.topics)


@router.message(BloggerRegistrationStates.topics)
async def handle_topics(message: Message, state: FSMContext) -> None:
    """Store blogger topics."""

    raw = (message.text or "").strip()
    topics = [
        topic.strip().lower() for topic in raw.split(",") if topic.strip()
    ]
    err = validate_topics(topics)
    if err is not None:
        await message.answer(err, reply_markup=support_keyboard())
        return
    await state.update_data(topics={"selected": topics})

    await message.answer(
        "Кто в основном смотрит ваш контент? По наблюдениям или статистике",
        reply_markup=with_support_keyboard(
            keyboard=[
                [KeyboardButton(text="👩 В основном женщины")],
                [KeyboardButton(text="👨 В основном мужчины")],
                [KeyboardButton(text="👥 Примерно поровну")],
            ],
        ),
    )
    await state.set_state(BloggerRegistrationStates.audience_gender)


@router.message(BloggerRegistrationStates.audience_gender)
async def handle_gender(message: Message, state: FSMContext) -> None:
    """Store audience gender."""

    gender_text = (message.text or "").strip()
    gender_map = {
        "в основном женщины": AudienceGender.FEMALE,
        "в основном мужчины": AudienceGender.MALE,
        "примерно поровну": AudienceGender.ALL,
    }
    key = gender_text[2:].lower()
    if key not in gender_map:
        await message.answer(
            "Выберите: В основном женщины, мужчины или Примерно поровну."
        )
        return

    await state.update_data(audience_gender=gender_map[key])
    await message.answer(
        "Основной возраст вашей аудитории?",
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
    await state.set_state(BloggerRegistrationStates.audience_age)


_AGE_BUTTONS: dict[str, tuple[int, int]] = {
    "до 18": (1, 17),
    "18–24": (18, 24),
    "25–34": (25, 34),
    "35–44": (35, 44),
    "45+": (45, 99),
}


@router.message(BloggerRegistrationStates.audience_age)
async def handle_age(message: Message, state: FSMContext) -> None:
    """Store audience age from button choice."""

    raw = (message.text or "").strip()
    if raw not in _AGE_BUTTONS:
        await message.answer("Выберите одну из кнопок возраста.")
        return

    min_age, max_age = _AGE_BUTTONS[raw]
    await state.update_data(audience_age_min=min_age, audience_age_max=max_age)
    await message.answer(
        "Где находится основная аудитория? Укажите до 3 городов через запятую: "
        "Москва, Казань, Санкт‑Петербург",
        reply_markup=support_keyboard(),
    )
    await state.set_state(BloggerRegistrationStates.audience_geo)


@router.message(BloggerRegistrationStates.audience_geo)
async def handle_geo(message: Message, state: FSMContext) -> None:
    """Store audience geography (up to 3 cities)."""

    geo = (message.text or "").strip()
    err = validate_audience_geo(geo)
    if err is not None:
        await message.answer(err, reply_markup=support_keyboard())
        return

    cities = [c.strip() for c in geo.split(",") if c.strip()]
    if len(cities) > 3:
        await message.answer(
            "Укажите не более 3 городов через запятую.",
            reply_markup=support_keyboard(),
        )
        return

    await state.update_data(audience_geo=geo)
    await message.answer(
        "Сколько стоит 1 UGC‑видео? Укажите цену в рублях: 500, 1000, 2000",
        reply_markup=support_keyboard(),
    )
    await state.set_state(BloggerRegistrationStates.price)


@router.message(BloggerRegistrationStates.price)
async def handle_price(message: Message, state: FSMContext) -> None:
    """Store price."""

    raw = (message.text or "").replace(",", ".").strip()
    try:
        price = float(raw)
    except ValueError:
        await message.answer("Введите число, например 500, 1000, 2000.")
        return

    err = validate_price(price, MAX_ORDER_PRICE)
    if err is not None:
        await message.answer(err, reply_markup=support_keyboard())
        return

    await state.update_data(price=price)
    await message.answer(
        "Иногда вы готовы работать с брендами по бартеру?",
        reply_markup=with_support_keyboard(
            keyboard=[
                [KeyboardButton(text="Да")],
                [KeyboardButton(text="Нет")],
            ],
        ),
    )
    await state.set_state(BloggerRegistrationStates.barter)


@router.message(BloggerRegistrationStates.barter)
async def handle_barter(message: Message, state: FSMContext) -> None:
    """Store barter preference."""

    text = (message.text or "").strip().lower()
    if text == "да":
        barter = True
    elif text == "нет":
        barter = False
    else:
        await message.answer("Выберите Да или Нет.")
        return

    await state.update_data(barter=barter)
    await message.answer(
        "Помимо UGC, как ещё вы готовы работать с брендами?",
        reply_markup=with_support_keyboard(
            keyboard=[
                [KeyboardButton(text=WORK_FORMAT_ADS_BUTTON_TEXT)],
                [KeyboardButton(text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT)],
            ],
        ),
    )
    await state.set_state(BloggerRegistrationStates.work_format)


@router.message(BloggerRegistrationStates.work_format)
async def handle_work_format(
    message: Message,
    state: FSMContext,
    config: AppConfig,
) -> None:
    """Store work format and show agreements step."""

    text = (message.text or "").strip()
    if text == WORK_FORMAT_ADS_BUTTON_TEXT:
        work_format = WorkFormat.ADS_IN_ACCOUNT
    elif text == WORK_FORMAT_UGC_ONLY_BUTTON_TEXT:
        work_format = WorkFormat.UGC_ONLY
    else:
        await message.answer(
            "Выберите одну из кнопок: Размещать рекламу у себя в аккаунте "
            "или Только UGC (без размещения)."
        )
        return

    await state.update_data(work_format=work_format)

    agreements_text = format_agreements_message(
        config,
        intro="Пожалуйста, ознакомьтесь с документами и подтвердите согласие.",
    )
    await message.answer(
        agreements_text,
        parse_mode="HTML",
        reply_markup=with_support_keyboard(
            keyboard=[[KeyboardButton(text=CONFIRM_AGREEMENT_BUTTON_TEXT)]],
        ),
    )
    await state.set_state(BloggerRegistrationStates.agreements)


@router.message(BloggerRegistrationStates.agreements)
async def handle_agreements(
    message: Message,
    state: FSMContext,
    blogger_registration_service: BloggerRegistrationService,
    user_role_service: UserRoleService,
) -> None:
    """Finalize registration after user confirms agreement via button."""

    if (message.text or "").strip() != CONFIRM_AGREEMENT_BUTTON_TEXT:
        await message.answer("Нажмите кнопку «Подтвердить согласие».")
        return

    data = await state.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await message.answer("Сессия истекла. Начните заново.")
        return
    try:
        telegram_username = (
            message.from_user.username if message.from_user else None
        )
        await user_role_service.set_user(
            external_id=data["external_id"],
            messenger_type=MessengerType.TELEGRAM,
            username=data["nickname"],
            telegram_username=telegram_username,
        )
        await blogger_registration_service.register_blogger(
            user_id=user_id,
            instagram_url=data["instagram_url"],
            city=data["city"],
            topics=data["topics"],
            audience_gender=data["audience_gender"],
            audience_age_min=data["audience_age_min"],
            audience_age_max=data["audience_age_max"],
            audience_geo=data["audience_geo"],
            price=data["price"],
            barter=data["barter"],
            work_format=data["work_format"],
        )
    except Exception as exc:
        error_str = str(exc)
        if "UniqueViolation" in error_str and "instagram_url" in error_str:
            logger.warning(
                "Instagram URL already exists",
                extra={
                    "user_id": data.get("user_id"),
                    "instagram_url": data.get("instagram_url"),
                },
            )
            await message.answer(
                "Этот Instagram уже зарегистрирован. "
                "Используйте другой или обратитесь в поддержку."
            )
            return
        raise

    await state.clear()
    profile_created_text = (
        "Профиль создан 👍\n\n"
        "Остался последний шаг — подтвердить Instagram‑аккаунт.\n"
        "Это нужно, чтобы:\n"
        "— защитить бренды от фейков\n"
        "— повысить доверие к вашему профилю\n"
        "— быстрее получать заказы"
    )
    await message.answer(
        profile_created_text,
        reply_markup=blogger_after_registration_keyboard(),
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
