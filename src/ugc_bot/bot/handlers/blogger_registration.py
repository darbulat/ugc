"""Blogger registration flow handlers."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.messenger.dto import Button
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
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    CREATE_PROFILE_BUTTON_TEXT,
    WORK_FORMAT_ADS_BUTTON_TEXT,
    WORK_FORMAT_UGC_ONLY_BUTTON_TEXT,
    blogger_after_registration_keyboard,
    creator_filled_profile_keyboard,
    creator_start_keyboard,
    flow_keyboard,
    flow_keyboard_remove,
)
from ugc_bot.bot.handlers.profile import INSTAGRAM_URL_REGEX
from ugc_bot.bot.handlers.start import CREATOR_LABEL
from ugc_bot.bot.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
    handle_role_choice,
    parse_user_id_from_state,
    resolve_messenger_dependencies,
)
from ugc_bot.bot.validators import (
    normalize_instagram_url,
    validate_audience_geo,
    validate_city,
    validate_nickname,
    validate_price,
    validate_topics,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    MessengerType,
    WorkFormat,
)
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

router = Router()
logger = logging.getLogger(__name__)

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

    await state_store.update_data(
        user_id=user.user_id, external_id=user.external_id
    )
    if user.username and len(user.username.strip()) >= 2:
        await state_store.update_data(nickname=user.username)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Прикрепите ссылку на инстаграмм в формате instagram.com/name"
            ),
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(BloggerRegistrationStates.instagram.state)
    else:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Введите ваше имя:",
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(BloggerRegistrationStates.name.state)


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
    """Start blogger registration flow via Create profile button."""

    await _start_registration_flow(
        message,
        state,
        user_role_service,
        messenger_client,
        event_adapter,
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
        text="Укажите ваш пол:",
        keyboard=flow_keyboard(
            keyboard=[
                [Button(text="Мужской")],
                [Button(text="Женский")],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.blogger_gender.state)


@router.message(BloggerRegistrationStates.blogger_gender)
async def handle_blogger_gender(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store blogger gender."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    text = (incoming.text or "").strip()
    if text == "Мужской":
        blogger_gender = BloggerGender.MALE
    elif text == "Женский":
        blogger_gender = BloggerGender.FEMALE
    else:
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
        keyboard=flow_keyboard(
            keyboard=[
                [Button(text="👩 В основном женщины")],
                [Button(text="👨 В основном мужчины")],
                [Button(text="👥 Примерно поровну")],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.audience_gender.state)


@router.message(BloggerRegistrationStates.audience_gender)
async def handle_gender(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience gender."""
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
    key = gender_text[2:].lower()
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
        keyboard=flow_keyboard(
            keyboard=[
                [Button(text="до 18")],
                [Button(text="18–24")],
                [Button(text="25–34")],
                [Button(text="35–44")],
                [Button(text="45+")],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.audience_age.state)


_AGE_BUTTONS: dict[str, tuple[int, int]] = {
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
    """Store audience age from button choice."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    raw = (incoming.text or "").strip()
    if raw not in _AGE_BUTTONS:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Выберите одну из кнопок возраста.",
        )
        return

    min_age, max_age = _AGE_BUTTONS[raw]
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
        keyboard=flow_keyboard(
            keyboard=[
                [Button(text="Да")],
                [Button(text="Нет")],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.barter.state)


@router.message(BloggerRegistrationStates.barter)
async def handle_barter(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store barter preference."""
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
        keyboard=flow_keyboard(
            keyboard=[
                [Button(text=WORK_FORMAT_ADS_BUTTON_TEXT)],
                [Button(text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT)],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.work_format.state)


@router.message(BloggerRegistrationStates.work_format)
async def handle_work_format(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store work format and show agreements step."""
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

    agreements_text = format_agreements_message(
        config,
        intro="Пожалуйста, ознакомьтесь с документами и подтвердите согласие.",
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=agreements_text,
        parse_mode="HTML",
        keyboard=flow_keyboard(
            keyboard=[[Button(text=CONFIRM_AGREEMENT_BUTTON_TEXT)]],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.agreements.state)


@router.message(BloggerRegistrationStates.agreements)
async def handle_agreements(
    message: Message,
    state: FSMContext,
    blogger_registration_service: BloggerRegistrationService,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Finalize registration after user confirms agreement via button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    if (incoming.text or "").strip() != CONFIRM_AGREEMENT_BUTTON_TEXT:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Нажмите кнопку «Подтвердить согласие».",
            keyboard=flow_keyboard(
                keyboard=[[Button(text=CONFIRM_AGREEMENT_BUTTON_TEXT)]],
            ),
        )
        return

    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Сессия истекла. Начните заново.",
        )
        return
    try:
        telegram_username = incoming.user.username
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
            blogger_gender=data["blogger_gender"],
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
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=(
                    "Этот Instagram уже зарегистрирован. "
                    "Используйте другой или обратитесь в поддержку."
                ),
            )
            return
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
