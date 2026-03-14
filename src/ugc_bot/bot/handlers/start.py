"""Start and role selection handlers."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    Keyboard,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.messenger.state import StateStore
from ugc_bot.application.ports import CountryRepository, LanguageRepository
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.filters import TextEqualsKey
from ugc_bot.bot.handlers.keyboards import (
    CALLBACK_CHANGE_ROLE,
    CALLBACK_COUNTRY_PREFIX,
    CALLBACK_LANG_PREFIX,
    CALLBACK_SUPPORT,
    advertiser_menu_inline_keyboard,
    build_support_telegram_url,
    country_inline_keyboard,
    language_inline_keyboard,
    main_menu_inline_keyboard,
    miniapp_open_inline_keyboard,
    role_inline_keyboard,
)
from ugc_bot.bot.handlers.utils import resolve_messenger_dependencies
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

router = Router()


@router.message(Command("app"))
async def app_miniapp_command(
    message: Message,
    config: AppConfig,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Send a message with button to open Mini App (registration and orders)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    base_url = getattr(config.webhook, "webhook_base_url", None) or ""
    if not base_url:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Mini App временно недоступен.",
        )
        return
    keyboard = miniapp_open_inline_keyboard(base_url)
    if not keyboard.rows:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Mini App временно недоступен.",
        )
        return
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Откройте приложение для регистрации и создания заказов.",
        keyboard=keyboard,
    )


@router.message(CommandStart())
async def start_command(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    referral_service: ReferralService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    country_repo: CountryRepository | None = None,
    language_repo: LanguageRepository | None = None,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle the /start command. Clears FSM so user always sees role."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)

    # Detect Telegram UI language for new users (language not yet set).
    # Use language_code directly without filtering by supported_codes so that
    # kk, be, uz etc. are picked up even if not yet seeded in the languages
    # table.
    tg_lang: str | None = None
    if message.from_user and message.from_user.language_code:
        tg_lang = message.from_user.language_code.split("-")[0].lower()

    # Use detected locale for text generation if user has no language set yet
    locale = (
        tg_lang
        if tg_lang and user_locale == config.market.default_locale
        else user_locale
    )

    start_text = (
        (await bot_texts_service.get("start_message", locale)).strip()
        or (config.market.start_text or "").strip()
        or ""
    )
    if not start_text:
        start_text = (
            "UMC — сервис для UGC.\n"
            "Бизнесу — подбор креаторов, креаторам — заказы."
        )
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], locale
    )
    country_prompt = (
        await bot_texts_service.get("country_prompt", locale)
    ).strip() or "Выберите вашу страну:"
    countries = await country_repo.list_enabled() if country_repo else []
    await _start_command(
        incoming=incoming,
        state_store=AiogramStateStore(state),
        messenger_client=messenger_client,
        user_role_service=user_role_service,
        referral_service=referral_service,
        start_text=start_text,
        role_kb=role_inline_keyboard(texts),
        country_prompt=country_prompt,
        country_kb=country_inline_keyboard(countries),
        tg_language_code=tg_lang,
    )


@router.callback_query(lambda c: c.data.startswith(CALLBACK_COUNTRY_PREFIX))
async def country_selected(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    country_repo: CountryRepository | None = None,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle country selection callback — save country, show role keyboard."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    existing_user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    if existing_user and existing_user.country is not None:
        return
    country_code = (callback.data or "").removeprefix(CALLBACK_COUNTRY_PREFIX)
    if not country_code:
        return
    if country_repo:
        country = await country_repo.get_by_code(country_code)
        if country is None:
            return
    await user_role_service.set_country(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
        country_code=country_code,
    )
    if incoming.message_id:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )
    locale = user_locale
    start_text = (
        (await bot_texts_service.get("start_message", locale)).strip()
        or (config.market.start_text or "").strip()
        or ""
    )
    if not start_text:
        start_text = (
            "UMC — сервис для UGC.\n"
            "Бизнесу — подбор креаторов, креаторам — заказы."
        )
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], locale
    )
    await AiogramStateStore(state).clear()
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=start_text,
        keyboard=role_inline_keyboard(texts),
    )


@router.callback_query(lambda c: c.data.startswith(CALLBACK_LANG_PREFIX))
async def language_selected(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    country_repo: CountryRepository | None = None,
    language_repo: LanguageRepository | None = None,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle language selection — save language, proceed to country or role."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    language_code = (callback.data or "").removeprefix(CALLBACK_LANG_PREFIX)
    if not language_code:
        return
    if language_repo is not None:
        valid_language = await language_repo.get_by_code(language_code)
        if valid_language is None:
            return
    try:
        user = await user_role_service.set_language(
            external_id=incoming.user.external_id,
            messenger_type=incoming.user.messenger_type,
            language_code=language_code,
        )
    except UserNotFoundError:
        return
    new_locale = language_code
    if incoming.message_id:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )
    if user and user.country is None and country_repo:
        countries = await country_repo.list_enabled()
        country_prompt = (
            await bot_texts_service.get("country_prompt", new_locale)
        ).strip() or "Выберите вашу страну:"
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=country_prompt,
            keyboard=country_inline_keyboard(countries),
        )
        return
    start_text = (
        await bot_texts_service.get("start_message", new_locale)
    ).strip() or "UGC — сервис для UGC."
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], new_locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=start_text,
        keyboard=role_inline_keyboard(texts),
    )


@router.message(Command("language"))
async def language_command(
    message: Message,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    language_repo: LanguageRepository | None = None,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle /language — show language selection keyboard."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    languages = await language_repo.list_enabled() if language_repo else []
    language_prompt = (
        await bot_texts_service.get("language_prompt", user_locale)
    ).strip() or "Выберите язык / Choose language:"
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=language_prompt,
        keyboard=language_inline_keyboard(languages),
    )


@router.callback_query(lambda c: c.data == CALLBACK_CHANGE_ROLE)
async def change_role_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle Change role inline button — show start screen again."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    locale = user_locale
    start_text = (
        (await bot_texts_service.get("start_message", locale)).strip()
        or (config.market.start_text or "").strip()
        or ""
    )
    if not start_text:
        start_text = (
            "UMC — сервис для UGC.\n"
            "Бизнесу — подбор креаторов, креаторам — заказы."
        )
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], locale
    )
    await _change_role_button(
        incoming=incoming,
        state_store=AiogramStateStore(state),
        messenger_client=messenger_client,
        start_text=start_text,
        role_kb=role_inline_keyboard(texts),
    )


@router.message(Command("role"))
@router.message(TextEqualsKey("btn_change_role"))
async def change_role_button(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle /role and 'Смена роли' — show start screen again."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = user_locale
    start_text = (
        (await bot_texts_service.get("start_message", locale)).strip()
        or (config.market.start_text or "").strip()
        or ""
    )
    if not start_text:
        start_text = (
            "UMC — сервис для UGC.\n"
            "Бизнесу — подбор креаторов, креаторам — заказы."
        )
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], locale
    )
    await _change_role_button(
        incoming=incoming,
        state_store=AiogramStateStore(state),
        messenger_client=messenger_client,
        start_text=start_text,
        role_kb=role_inline_keyboard(texts),
    )


@router.callback_query(lambda c: c.data == CALLBACK_SUPPORT)
async def support_callback(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle Support inline button — clear FSM, send support text."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    locale = user_locale
    support_text = (
        await bot_texts_service.get("support_response", locale)
    ).strip()
    if not support_text:
        support_text = (config.market.support_response_text or "").strip()
    if not support_text and (config.market.support_contact or "").strip():
        support_text = (
            f"Служба поддержки: {config.market.support_contact.strip()}\n"
            "Обращайтесь по любым вопросам!"
        )
    if not support_text:
        support_text = (
            "Служба поддержки: @usemycontent\nОбращайтесь по любым вопросам!"
        )
    menu_texts = await bot_texts_service.get_many(
        [
            "btn_support",
            "btn_change_role",
            "btn_create_order",
            "btn_my_orders",
            "btn_my_profile",
            "btn_edit_profile",
        ],
        locale,
    )
    support_url = build_support_telegram_url(
        config.market.support_contact or ""
    )
    await _support_button(
        incoming=incoming,
        user_role_service=user_role_service,
        profile_service=profile_service,
        state_store=AiogramStateStore(state),
        messenger_client=messenger_client,
        support_text=support_text,
        menu_texts=menu_texts,
        support_url=support_url,
    )


@router.message(Command("support"))
@router.message(TextEqualsKey("btn_support"))
async def support_button(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle Support: clear FSM, send support text."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = user_locale
    support_text = (
        await bot_texts_service.get("support_response", locale)
    ).strip()
    if not support_text:
        support_text = (config.market.support_response_text or "").strip()
    if not support_text and (config.market.support_contact or "").strip():
        support_text = (
            f"Служба поддержки: {config.market.support_contact.strip()}\n"
            "Обращайтесь по любым вопросам!"
        )
    if not support_text:
        support_text = (
            "Служба поддержки: @usemycontent\nОбращайтесь по любым вопросам!"
        )
    menu_texts = await bot_texts_service.get_many(
        [
            "btn_support",
            "btn_change_role",
            "btn_create_order",
            "btn_my_orders",
            "btn_my_profile",
            "btn_edit_profile",
        ],
        locale,
    )
    support_url = build_support_telegram_url(
        config.market.support_contact or ""
    )
    await _support_button(
        incoming=incoming,
        user_role_service=user_role_service,
        profile_service=profile_service,
        state_store=AiogramStateStore(state),
        messenger_client=messenger_client,
        support_text=support_text,
        menu_texts=menu_texts,
        support_url=support_url,
    )


async def _start_command(
    *,
    incoming: IncomingMessage,
    state_store: StateStore,
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
    referral_service: ReferralService,
    start_text: str,
    role_kb: Keyboard,
    country_prompt: str = "Выберите вашу страну:",
    country_kb: Keyboard | None = None,
    tg_language_code: str | None = None,
) -> None:
    """Handle the /start command. Clears FSM so /start always shows role."""
    if not incoming.user.external_id:
        return
    await state_store.clear()
    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    username = user.username if user else ""

    user = await user_role_service.set_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
        username=username,
        role_chosen=False,
        telegram_username=incoming.user.username,
    )
    referral_code = referral_service.parse_referral_code(incoming.text)
    if referral_code:
        await referral_service.save_pending_referral(
            user.user_id, referral_code
        )
    # Auto-set language from Telegram for new users who haven't chosen one yet.
    # Language can only be changed explicitly via the /language command.
    if user.language is None and tg_language_code:
        user = await user_role_service.set_language(
            external_id=incoming.user.external_id,
            messenger_type=incoming.user.messenger_type,
            language_code=tg_language_code,
        )
    # Step 1: Country
    if user.country is None and country_kb is not None and country_kb.rows:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=country_prompt,
            keyboard=country_kb,
        )
        return
    # Step 3: Role
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=start_text,
        keyboard=role_kb,
    )


async def _change_role_button(
    *,
    incoming: IncomingMessage | IncomingCallback,
    state_store: StateStore,
    messenger_client: MessengerClient,
    start_text: str,
    role_kb: Keyboard,
) -> None:
    """Handle /role and change-role button — show start screen again."""
    await state_store.clear()
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=start_text,
        keyboard=role_kb,
    )


async def _support_button(
    *,
    incoming: IncomingMessage | IncomingCallback,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state_store: StateStore,
    messenger_client: MessengerClient,
    support_text: str,
    menu_texts: dict[str, str],
    support_url: str | None = None,
) -> None:
    """Handle Support: clear FSM, send support text."""
    if not incoming.user.external_id:
        return
    await state_store.clear()

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    username = user.username if user else ""

    await user_role_service.set_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
        username=username,
        role_chosen=True,
        telegram_username=incoming.user.username,
    )

    advertiser = (
        await profile_service.get_advertiser_profile(user.user_id)
        if user
        else None
    )
    reply_markup = (
        advertiser_menu_inline_keyboard(menu_texts)
        if advertiser is not None
        else main_menu_inline_keyboard(menu_texts, support_url=support_url)
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=support_text,
        keyboard=reply_markup,
    )
