"""Start and role selection handlers."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ugc_bot.application.messenger.dto import IncomingMessage, Keyboard
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.messenger.state import StateStore
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.filters import TextEqualsKey
from ugc_bot.bot.handlers.keyboards import (
    advertiser_menu_keyboard,
    main_menu_keyboard,
    role_keyboard,
)
from ugc_bot.bot.handlers.utils import resolve_messenger_dependencies
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

router = Router()


@router.message(CommandStart())
async def start_command(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    referral_service: ReferralService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle the /start command. Clears FSM so user always sees role."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = config.market.default_locale
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
    await _start_command(
        incoming=incoming,
        state_store=AiogramStateStore(state),
        messenger_client=messenger_client,
        user_role_service=user_role_service,
        referral_service=referral_service,
        start_text=start_text,
        role_kb=role_keyboard(texts),
    )


@router.message(Command("role"))
@router.message(TextEqualsKey("btn_change_role"))
async def change_role_button(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle /role and 'Смена роли' — show start screen again."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = config.market.default_locale
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
        role_kb=role_keyboard(texts),
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
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle Support: clear FSM, send support text."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = config.market.default_locale
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
    await _support_button(
        incoming=incoming,
        user_role_service=user_role_service,
        profile_service=profile_service,
        state_store=AiogramStateStore(state),
        messenger_client=messenger_client,
        support_text=support_text,
        menu_texts=menu_texts,
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
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=start_text,
        keyboard=role_kb,
    )


async def _change_role_button(
    *,
    incoming: IncomingMessage,
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
    incoming: IncomingMessage,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state_store: StateStore,
    messenger_client: MessengerClient,
    support_text: str,
    menu_texts: dict[str, str],
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
        advertiser_menu_keyboard(menu_texts)
        if advertiser is not None
        else main_menu_keyboard(menu_texts)
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=support_text,
        keyboard=reply_markup,
    )
