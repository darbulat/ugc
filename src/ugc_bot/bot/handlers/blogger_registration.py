"""Blogger registration flow handlers."""

import logging
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.messenger.dto import Button, IncomingCallback
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    CALLBACK_BLOGGER_AGE_0_17,
    CALLBACK_BLOGGER_AGE_18_24,
    CALLBACK_BLOGGER_AGE_25_34,
    CALLBACK_BLOGGER_AGE_35_44,
    CALLBACK_BLOGGER_AGE_45_99,
    CALLBACK_BLOGGER_AGREE,
    CALLBACK_BLOGGER_AUDIENCE_A,
    CALLBACK_BLOGGER_AUDIENCE_F,
    CALLBACK_BLOGGER_AUDIENCE_M,
    CALLBACK_BLOGGER_BARTER_N,
    CALLBACK_BLOGGER_BARTER_Y,
    CALLBACK_BLOGGER_GENDER_F,
    CALLBACK_BLOGGER_GENDER_M,
    CALLBACK_BLOGGER_WORK_ADS,
    CALLBACK_BLOGGER_WORK_UGC,
    CALLBACK_CREATOR_CREATE,
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    CREATE_PROFILE_BUTTON_TEXT,
    WORK_FORMAT_ADS_BUTTON_TEXT,
    WORK_FORMAT_UGC_ONLY_BUTTON_TEXT,
    blogger_after_registration_keyboard,
    confirm_agreement_inline_keyboard,
    creator_filled_profile_keyboard,
    creator_start_keyboard,
    flow_inline_keyboard,
    flow_keyboard_remove,
)
from ugc_bot.bot.handlers.profile import INSTAGRAM_URL_REGEX
from ugc_bot.bot.handlers.start import CREATOR_LABEL
from ugc_bot.bot.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    handle_role_choice,
    parse_user_id_from_state,
    resolve_messenger_dependencies,
)
from ugc_bot.bot.validators import (
    normalize_instagram_url,
    validate_audience_geo,
    validate_birth_date,
    validate_city,
    validate_nickname,
    validate_price,
    validate_topics,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    WorkFormat,
)
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

router = Router()
logger = logging.getLogger(__name__)


async def _remove_inline_keyboard_from_callback(
    incoming: IncomingCallback,
    messenger_client: MessengerClient,
) -> None:
    """Remove inline keyboard from the message that triggered the callback."""
    if incoming.message_id:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )


CREATOR_CHOOSE_ACTION_TEXT = "Выберите действие:"
CREATOR_INTRO_NOT_REGISTERED = (
    "Ты — UGC‑креатор.\n"
    "После регистрации бренды смогут находить тебя и отправлять предложения."
)


class BloggerRegistrationStates(StatesGroup):
    """States for blogger registration."""

    name = State()
    instagram = State()
    city = State()
    birth_date = State()
    blogger_gender = State()
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
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle 'Я креатор': persist role and show menu or registration prompt."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    await handle_role_choice(
        incoming,
        messenger_client,
        user_role_service,
        AiogramStateStore(state),
        profile_getter=profile_service.get_blogger_profile,
        choose_action_text=CREATOR_CHOOSE_ACTION_TEXT,
        intro_text=CREATOR_INTRO_NOT_REGISTERED,
        menu_keyboard=creator_filled_profile_keyboard,
        start_keyboard=creator_start_keyboard,
    )


async def _start_registration_flow_impl(
    chat_id: str,
    state_store: AiogramStateStore,
    user: object,
    messenger_client: MessengerClient,
) -> None:
    """Start blogger registration: first step (name or instagram)."""
    user_id = getattr(user, "user_id", None)
    external_id = getattr(user, "external_id", None)
    username = getattr(user, "username", None) or ""
    await state_store.update_data(user_id=user_id, external_id=external_id)
    if username and len(username.strip()) >= 2:
        await state_store.update_data(nickname=username)
        await messenger_client.send_text(
            chat_id=chat_id,
            text=(
                "Прикрепите ссылку на инстаграмм в формате instagram.com/name"
            ),
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(BloggerRegistrationStates.instagram.state)
    else:
        await messenger_client.send_text(
            chat_id=chat_id,
            text="Введите ваше имя:",
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(BloggerRegistrationStates.name.state)


async def _start_registration_flow(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start blogger registration: first step (name)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Начните с /start.",
        blocked_msg="Заблокированные пользователи не могут регистрироваться.",
        pause_msg="Пользователи на паузе не могут регистрироваться.",
    )
    if user is None:
        return
    await _start_registration_flow_impl(
        incoming.chat_id, state_store, user, messenger_client
    )


@router.message(
    lambda msg: (msg.text or "").strip() == CREATE_PROFILE_BUTTON_TEXT
)
async def start_registration_button(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start blogger registration via message (e.g. tests or legacy reply)."""
    await _start_registration_flow(
        message, state, user_role_service, messenger_client, event_adapter
    )


@router.callback_query(lambda c: c.data == CALLBACK_CREATOR_CREATE)
async def start_registration_inline(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start blogger registration flow via Inline Create profile button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Начните с /start.",
        blocked_msg="Заблокированные пользователи не могут регистрироваться.",
        pause_msg="Пользователи на паузе не могут регистрироваться.",
    )
    if user is None:
        return
    state_store = AiogramStateStore(state)
    await _start_registration_flow_impl(
        incoming.chat_id, state_store, user, messenger_client
    )


@router.message(BloggerRegistrationStates.name)
async def handle_name(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store nickname."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    nickname = (incoming.text or "").strip()
    err = validate_nickname(nickname)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(nickname=nickname)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Прикрепите ссылку на инстаграмм в формате instagram.com/name",
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.instagram.state)


@router.message(BloggerRegistrationStates.instagram)
async def handle_instagram(
    message: Message,
    state: FSMContext,
    blogger_registration_service: BloggerRegistrationService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store Instagram URL."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    instagram_url = normalize_instagram_url((incoming.text or "").strip())
    if not instagram_url:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Ссылка не может быть пустой. Введите снова:",
        )
        return
    if "instagram.com/" not in instagram_url.lower():
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Неверный формат ссылки. Прикрепите instagram.com/name",
        )
        return
    if not INSTAGRAM_URL_REGEX.match(instagram_url):
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Неверный формат ссылки Instagram. Пример: https://instagram.com/name"
            ),
        )
        return

    # Check if Instagram URL is already taken
    existing_profile = (
        await blogger_registration_service.get_profile_by_instagram_url(
            instagram_url
        )
    )
    if existing_profile is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Этот Instagram аккаунт уже зарегистрирован. "
                "Пожалуйста, используйте другой аккаунт "
                "или обратитесь в поддержку."
            ),
        )
        return

    await state_store.update_data(instagram_url=instagram_url)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Из какого вы города?\nПример: Казань / Москва / Санкт‑Петербург",
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.city.state)


@router.message(BloggerRegistrationStates.city)
async def handle_city(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store creator city."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    city = (incoming.text or "").strip()
    err = validate_city(city, required=True)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(city=city)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "Укажите дату рождения в формате ДД.ММ.ГГГГ "
            "(например 15.05.1995):"
        ),
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.birth_date.state)


@router.message(BloggerRegistrationStates.birth_date)
async def handle_birth_date(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store creator birth date and ask for gender."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    text = (incoming.text or "").strip()
    parsed_date, err = validate_birth_date(text)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return
    assert parsed_date is not None
    await state_store.update_data(birth_date=parsed_date.isoformat())
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Укажите ваш пол:",
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text="Мужской", callback_data=CALLBACK_BLOGGER_GENDER_M
                    ),
                    Button(
                        text="Женский", callback_data=CALLBACK_BLOGGER_GENDER_F
                    ),
                ],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.blogger_gender.state)


def _blogger_gender_from_callback(data: str) -> BloggerGender | None:
    """Map callback_data to BloggerGender."""
    if data == CALLBACK_BLOGGER_GENDER_M:
        return BloggerGender.MALE
    if data == CALLBACK_BLOGGER_GENDER_F:
        return BloggerGender.FEMALE
    return None


@router.callback_query(
    lambda c: c.data in (CALLBACK_BLOGGER_GENDER_M, CALLBACK_BLOGGER_GENDER_F)
)
async def handle_blogger_gender_callback(
    callback: CallbackQuery,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store blogger gender from inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.blogger_gender.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    blogger_gender = _blogger_gender_from_callback(incoming.data or "")
    if blogger_gender is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    await state_store.update_data(blogger_gender=blogger_gender)
    topics_text = (
        "О чём ваш контент?\n"
        "Напишите 1–3 тематики через запятую: бизнес, инвестиции, фитнес, "
        "питание, бьюти, уход за кожей, путешествия, еда, рестораны, мода, "
        "стиль, дети, семья, технологии, гаджеты, лайфстайл, другое"
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=topics_text,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.topics.state)


@router.message(BloggerRegistrationStates.blogger_gender)
async def handle_blogger_gender(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store blogger gender from message text (e.g. tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    text = (incoming.text or "").strip()
    blogger_gender = None
    if text == "Мужской":
        blogger_gender = BloggerGender.MALE
    elif text == "Женский":
        blogger_gender = BloggerGender.FEMALE
    if blogger_gender is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Выберите одну из кнопок: Мужской или Женский.",
        )
        return
    await state_store.update_data(blogger_gender=blogger_gender)
    topics_text = (
        "О чём ваш контент?\n"
        "Напишите 1–3 тематики через запятую: бизнес, инвестиции, фитнес, "
        "питание, бьюти, уход за кожей, путешествия, еда, рестораны, мода, "
        "стиль, дети, семья, технологии, гаджеты, лайфстайл, другое"
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=topics_text,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.topics.state)


@router.message(BloggerRegistrationStates.topics)
async def handle_topics(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store blogger topics."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    raw = (incoming.text or "").strip()
    topics = [
        topic.strip().lower() for topic in raw.split(",") if topic.strip()
    ]
    err = validate_topics(topics)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return
    await state_store.update_data(topics={"selected": topics})

    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "Кто в основном смотрит ваш контент? "
            "По наблюдениям или статистике"
        ),
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text="👩 В основном женщины",
                        callback_data=CALLBACK_BLOGGER_AUDIENCE_F,
                    )
                ],
                [
                    Button(
                        text="👨 В основном мужчины",
                        callback_data=CALLBACK_BLOGGER_AUDIENCE_M,
                    )
                ],
                [
                    Button(
                        text="👥 Примерно поровну",
                        callback_data=CALLBACK_BLOGGER_AUDIENCE_A,
                    )
                ],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.audience_gender.state)


def _audience_gender_from_callback(data: str) -> AudienceGender | None:
    """Map callback_data to AudienceGender."""
    if data == CALLBACK_BLOGGER_AUDIENCE_F:
        return AudienceGender.FEMALE
    if data == CALLBACK_BLOGGER_AUDIENCE_M:
        return AudienceGender.MALE
    if data == CALLBACK_BLOGGER_AUDIENCE_A:
        return AudienceGender.ALL
    return None


@router.callback_query(
    lambda c: c.data
    in (
        CALLBACK_BLOGGER_AUDIENCE_F,
        CALLBACK_BLOGGER_AUDIENCE_M,
        CALLBACK_BLOGGER_AUDIENCE_A,
    )
)
async def handle_audience_gender_callback(
    callback: CallbackQuery,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience gender from inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.audience_gender.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    audience_gender = _audience_gender_from_callback(incoming.data or "")
    if audience_gender is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    await state_store.update_data(audience_gender=audience_gender)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Основной возраст вашей аудитории?",
        keyboard=flow_inline_keyboard(
            rows=[
                [Button(text="до 18", callback_data=CALLBACK_BLOGGER_AGE_0_17)],
                [
                    Button(
                        text="18–24", callback_data=CALLBACK_BLOGGER_AGE_18_24
                    )
                ],
                [
                    Button(
                        text="25–34", callback_data=CALLBACK_BLOGGER_AGE_25_34
                    )
                ],
                [
                    Button(
                        text="35–44", callback_data=CALLBACK_BLOGGER_AGE_35_44
                    )
                ],
                [Button(text="45+", callback_data=CALLBACK_BLOGGER_AGE_45_99)],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.audience_age.state)


@router.message(BloggerRegistrationStates.audience_gender)
async def handle_gender(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience gender from message text (e.g. tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    gender_text = (incoming.text or "").strip()
    gender_map = {
        "в основном женщины": AudienceGender.FEMALE,
        "в основном мужчины": AudienceGender.MALE,
        "примерно поровну": AudienceGender.ALL,
    }
    key = (
        gender_text[2:].lower() if len(gender_text) > 2 else gender_text.lower()
    )
    if key not in gender_map:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Выберите: В основном женщины, мужчины или Примерно поровну."
            ),
        )
        return
    await state_store.update_data(audience_gender=gender_map[key])
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Основной возраст вашей аудитории?",
        keyboard=flow_inline_keyboard(
            rows=[
                [Button(text="до 18", callback_data=CALLBACK_BLOGGER_AGE_0_17)],
                [
                    Button(
                        text="18–24",
                        callback_data=CALLBACK_BLOGGER_AGE_18_24,
                    )
                ],
                [
                    Button(
                        text="25–34",
                        callback_data=CALLBACK_BLOGGER_AGE_25_34,
                    )
                ],
                [
                    Button(
                        text="35–44",
                        callback_data=CALLBACK_BLOGGER_AGE_35_44,
                    )
                ],
                [Button(text="45+", callback_data=CALLBACK_BLOGGER_AGE_45_99)],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.audience_age.state)


_AGE_CALLBACK_TO_RANGE: dict[str, tuple[int, int]] = {
    CALLBACK_BLOGGER_AGE_0_17: (1, 17),
    CALLBACK_BLOGGER_AGE_18_24: (18, 24),
    CALLBACK_BLOGGER_AGE_25_34: (25, 34),
    CALLBACK_BLOGGER_AGE_35_44: (35, 44),
    CALLBACK_BLOGGER_AGE_45_99: (45, 99),
}

_AGE_TEXT_TO_RANGE: dict[str, tuple[int, int]] = {
    "до 18": (1, 17),
    "18–24": (18, 24),
    "25–34": (25, 34),
    "35–44": (35, 44),
    "45+": (45, 99),
}


@router.message(BloggerRegistrationStates.audience_age)
async def handle_age(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience age from message text (e.g. tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    raw = (incoming.text or "").strip()
    if raw not in _AGE_TEXT_TO_RANGE:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Выберите одну из кнопок возраста.",
        )
        return
    min_age, max_age = _AGE_TEXT_TO_RANGE[raw]
    await state_store.update_data(
        audience_age_min=min_age, audience_age_max=max_age
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "Где находится основная аудитория? "
            "Укажите до 3 городов через запятую: "
            "Москва, Казань, Санкт‑Петербург"
        ),
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.audience_geo.state)


@router.callback_query(
    lambda c: c.data in _AGE_CALLBACK_TO_RANGE,
)
async def handle_audience_age_callback(
    callback: CallbackQuery,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience age from inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.audience_age.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    data = incoming.data or ""
    if data not in _AGE_CALLBACK_TO_RANGE:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    min_age, max_age = _AGE_CALLBACK_TO_RANGE[data]
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    await state_store.update_data(
        audience_age_min=min_age, audience_age_max=max_age
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "Где находится основная аудитория? "
            "Укажите до 3 городов через запятую: "
            "Москва, Казань, Санкт‑Петербург"
        ),
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.audience_geo.state)


@router.message(BloggerRegistrationStates.audience_geo)
async def handle_geo(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience geography (up to 3 cities)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    geo = (incoming.text or "").strip()
    err = validate_audience_geo(geo)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    cities = [c.strip() for c in geo.split(",") if c.strip()]
    if len(cities) > 3:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Укажите не более 3 городов через запятую.",
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(audience_geo=geo)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "Сколько стоит 1 UGC‑видео? Укажите цену в рублях: 500, 1000, 2000"
        ),
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.price.state)


@router.message(BloggerRegistrationStates.price)
async def handle_price(
    message: Message,
    state: FSMContext,
    max_order_price: float,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store price."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    raw = (incoming.text or "").replace(",", ".").strip()
    try:
        price = float(raw)
    except ValueError:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Введите число, например 500, 1000, 2000.",
        )
        return

    err = validate_price(price, max_order_price)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(price=price)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Иногда вы готовы работать с брендами по бартеру?",
        keyboard=flow_inline_keyboard(
            rows=[
                [Button(text="Да", callback_data=CALLBACK_BLOGGER_BARTER_Y)],
                [Button(text="Нет", callback_data=CALLBACK_BLOGGER_BARTER_N)],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.barter.state)


@router.callback_query(
    lambda c: c.data in (CALLBACK_BLOGGER_BARTER_Y, CALLBACK_BLOGGER_BARTER_N),
)
async def handle_barter_callback(
    callback: CallbackQuery,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store barter preference from inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.barter.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    barter = incoming.data == CALLBACK_BLOGGER_BARTER_Y
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    await state_store.update_data(barter=barter)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Помимо UGC, как ещё вы готовы работать с брендами?",
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text=WORK_FORMAT_ADS_BUTTON_TEXT,
                        callback_data=CALLBACK_BLOGGER_WORK_ADS,
                    )
                ],
                [
                    Button(
                        text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT,
                        callback_data=CALLBACK_BLOGGER_WORK_UGC,
                    )
                ],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.work_format.state)


@router.message(BloggerRegistrationStates.barter)
async def handle_barter(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store barter preference from message text (e.g. tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    text = (incoming.text or "").strip().lower()
    if text == "да":
        barter = True
    elif text == "нет":
        barter = False
    else:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Выберите Да или Нет.",
        )
        return
    await state_store.update_data(barter=barter)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Помимо UGC, как ещё вы готовы работать с брендами?",
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text=WORK_FORMAT_ADS_BUTTON_TEXT,
                        callback_data=CALLBACK_BLOGGER_WORK_ADS,
                    )
                ],
                [
                    Button(
                        text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT,
                        callback_data=CALLBACK_BLOGGER_WORK_UGC,
                    )
                ],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.work_format.state)


def _work_format_from_callback(data: str) -> WorkFormat | None:
    """Map callback_data to WorkFormat."""
    if data == CALLBACK_BLOGGER_WORK_ADS:
        return WorkFormat.ADS_IN_ACCOUNT
    if data == CALLBACK_BLOGGER_WORK_UGC:
        return WorkFormat.UGC_ONLY
    return None


@router.callback_query(
    lambda c: c.data in (CALLBACK_BLOGGER_WORK_ADS, CALLBACK_BLOGGER_WORK_UGC),
)
async def handle_work_format_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    blogger_registration_service: BloggerRegistrationService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store work format from inline button, save profile, show agreements."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.work_format.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    work_format = _work_format_from_callback(incoming.data or "")
    if work_format is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    await state_store.update_data(work_format=work_format)
    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Сессия истекла. Начните заново.",
        )
        await state_store.clear()
        return

    try:
        telegram_username = getattr(incoming.user, "username", None)
        birth_date_raw = data.get("birth_date")
        birth_date_val = (
            date.fromisoformat(birth_date_raw) if birth_date_raw else None
        )
        await blogger_registration_service.save_blogger_before_agreement(
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
            work_format=work_format,
            blogger_gender=data["blogger_gender"],
            display_name=data.get("nickname"),
            telegram_username=telegram_username,
            birth_date=birth_date_val,
        )
    except Exception as exc:
        error_str = str(exc)
        is_duplicate = (
            "UniqueViolation" in error_str and "instagram_url" in error_str
        ) or "уже зарегистрирован" in error_str
        if is_duplicate:
            logger.warning(
                "Instagram URL already exists",
                extra={
                    "user_id": str(user_id),
                    "instagram_url": data.get("instagram_url"),
                },
            )
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=(
                    "Этот Instagram уже зарегистрирован. "
                    "Используйте другой или обратитесь в поддержку."
                ),
            )
            return
        raise

    agreements_text = format_agreements_message(
        config,
        intro="Пожалуйста, ознакомьтесь с документами и подтвердите согласие.",
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=agreements_text,
        parse_mode="HTML",
        keyboard=confirm_agreement_inline_keyboard(CALLBACK_BLOGGER_AGREE),
    )
    await state_store.set_state(BloggerRegistrationStates.agreements.state)


@router.message(BloggerRegistrationStates.work_format)
async def handle_work_format(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    blogger_registration_service: BloggerRegistrationService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store work format from message, save profile, show agreements (tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    text = (incoming.text or "").strip()
    if text == WORK_FORMAT_ADS_BUTTON_TEXT:
        work_format = WorkFormat.ADS_IN_ACCOUNT
    elif text == WORK_FORMAT_UGC_ONLY_BUTTON_TEXT:
        work_format = WorkFormat.UGC_ONLY
    else:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Выберите одну из кнопок: Размещать рекламу у себя в аккаунте "
                "или Только UGC (без размещения)."
            ),
        )
        return
    await state_store.update_data(work_format=work_format)
    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Сессия истекла. Начните заново.",
        )
        await state_store.clear()
        return
    try:
        telegram_username = getattr(incoming.user, "username", None)
        birth_date_raw = data.get("birth_date")
        birth_date_val = (
            date.fromisoformat(birth_date_raw) if birth_date_raw else None
        )
        await blogger_registration_service.save_blogger_before_agreement(
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
            work_format=work_format,
            blogger_gender=data["blogger_gender"],
            display_name=data.get("nickname"),
            telegram_username=telegram_username,
            birth_date=birth_date_val,
        )
    except Exception as exc:
        error_str = str(exc)
        is_duplicate = (
            "UniqueViolation" in error_str and "instagram_url" in error_str
        ) or "уже зарегистрирован" in error_str
        if is_duplicate:
            logger.warning(
                "Instagram URL already exists",
                extra={
                    "user_id": str(user_id),
                    "instagram_url": data.get("instagram_url"),
                },
            )
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=(
                    "Этот Instagram уже зарегистрирован. "
                    "Используйте другой или обратитесь в поддержку."
                ),
            )
            return
        raise
    agreements_text = format_agreements_message(
        config,
        intro="Пожалуйста, ознакомьтесь с документами и подтвердите согласие.",
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=agreements_text,
        parse_mode="HTML",
        keyboard=confirm_agreement_inline_keyboard(CALLBACK_BLOGGER_AGREE),
    )
    await state_store.set_state(BloggerRegistrationStates.agreements.state)


@router.callback_query(lambda c: c.data == CALLBACK_BLOGGER_AGREE)
async def handle_agreements_callback(
    callback: CallbackQuery,
    state: FSMContext,
    blogger_registration_service: BloggerRegistrationService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Finalize blogger registration after user confirms agreement (inline)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.agreements.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return

    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Сессия истекла. Начните заново.",
        )
        await state_store.clear()
        return
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    try:
        telegram_username = getattr(incoming.user, "username", None)
        await blogger_registration_service.confirm_blogger_agreement(
            user_id=user_id,
            telegram_username=telegram_username,
        )
    except Exception:
        raise

    await state_store.clear()
    profile_created_text = (
        "Профиль создан 👍\n\n"
        "Остался последний шаг — подтвердить Instagram‑аккаунт.\n"
        "Это нужно, чтобы:\n"
        "— защитить бренды от фейков\n"
        "— повысить доверие к вашему профилю\n"
        "— быстрее получать заказы"
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=profile_created_text,
        keyboard=blogger_after_registration_keyboard(),
    )


@router.message(BloggerRegistrationStates.agreements)
async def handle_agreements(
    message: Message,
    state: FSMContext,
    blogger_registration_service: BloggerRegistrationService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Finalize blogger registration after message Confirm agreement (tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    if (incoming.text or "").strip() != CONFIRM_AGREEMENT_BUTTON_TEXT:
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Регистрация прервана. Чтобы завершить, откройте «Мой профиль» "
                "и подтвердите согласие."
            ),
            keyboard=flow_keyboard_remove(),
        )
        return
    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Сессия истекла. Начните заново.",
        )
        await state_store.clear()
        return
    try:
        telegram_username = getattr(incoming.user, "username", None)
        await blogger_registration_service.confirm_blogger_agreement(
            user_id=user_id,
            telegram_username=telegram_username,
        )
    except Exception:
        raise
    await state_store.clear()
    profile_created_text = (
        "Профиль создан 👍\n\n"
        "Остался последний шаг — подтвердить Instagram‑аккаунт.\n"
        "Это нужно, чтобы:\n"
        "— защитить бренды от фейков\n"
        "— повысить доверие к вашему профилю\n"
        "— быстрее получать заказы"
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=profile_created_text,
        keyboard=blogger_after_registration_keyboard(),
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
