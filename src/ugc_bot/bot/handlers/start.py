"""Start and role selection handlers."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ugc_bot.application.messenger.dto import (
    Button,
    IncomingMessage,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.messenger.state import StateStore
from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    CHANGE_ROLE_BUTTON_TEXT,
    SUPPORT_BUTTON_TEXT,
    advertiser_menu_keyboard,
    main_menu_keyboard,
)
from ugc_bot.bot.handlers.utils import resolve_messenger_dependencies
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

router = Router()

START_TEXT = (
    "UMC — сервис для UGC.\n" "Бизнесу — подбор креаторов, креаторам — заказы."
)

SUPPORT_RESPONSE_TEXT = (
    "Служба поддержки: @usemycontent\n" "Обращайтесь по любым вопросам!"
)

CREATOR_LABEL = "Я креатор"
ADVERTISER_LABEL = "Мне нужны UGC‑креаторы"


@router.message(CommandStart())
async def start_command(
    message: Message,
    user_role_service: UserRoleService,
    referral_service: ReferralService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle the /start command."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    await _start_command(
        incoming=incoming,
        messenger_client=messenger_client,
        user_role_service=user_role_service,
        referral_service=referral_service,
    )


@router.message(Command("role"))
@router.message(lambda msg: msg.text == CHANGE_ROLE_BUTTON_TEXT)
async def change_role_button(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle /role and 'Смена роли' — show start screen again."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    await _change_role_button(
        incoming=incoming,
        state_store=AiogramStateStore(state),
        messenger_client=messenger_client,
    )


_STATE_TO_FLOW: dict[str, str] = {
    "BloggerRegistrationStates": "blogger_registration",
    "AdvertiserRegistrationStates": "advertiser_registration",
    "OrderCreationStates": "order_creation",
    "EditProfileStates": "edit_profile",
}


def _flow_type_from_state(state_key: str | None) -> str | None:
    """Return flow_type if state_key belongs to a draftable flow, else None."""
    if not state_key or ":" not in state_key:
        return None
    prefix = state_key.split(":")[0]
    return _STATE_TO_FLOW.get(prefix)


@router.message(Command("support"))
@router.message(lambda msg: (msg.text or "").strip() == SUPPORT_BUTTON_TEXT)
async def support_button(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state: FSMContext,
    fsm_draft_service: FsmDraftService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle Support: save draft if in flow, clear FSM, send support text."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    await _support_button(
        incoming=incoming,
        user_role_service=user_role_service,
        profile_service=profile_service,
        state_store=AiogramStateStore(state),
        fsm_draft_service=fsm_draft_service,
        messenger_client=messenger_client,
    )


def _role_keyboard() -> Keyboard:
    """Build a reply keyboard for role selection."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=CREATOR_LABEL)],
            [Button(text=ADVERTISER_LABEL)],
            [Button(text=SUPPORT_BUTTON_TEXT)],
        ],
        resize=True,
        one_time=True,
    )


async def _start_command(
    *,
    incoming: IncomingMessage,
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
    referral_service: ReferralService,
) -> None:
    """Handle the /start command."""
    if not incoming.user.external_id:
        return
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
        text=START_TEXT,
        keyboard=_role_keyboard(),
    )


async def _change_role_button(
    *,
    incoming: IncomingMessage,
    state_store: StateStore,
    messenger_client: MessengerClient,
) -> None:
    """Handle /role and 'Смена роли' — show start screen again."""
    await state_store.clear()
    await messenger_client.send_text(
        chat_id=incoming.chat_id, text=START_TEXT, keyboard=_role_keyboard()
    )


async def _support_button(
    *,
    incoming: IncomingMessage,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state_store: StateStore,
    fsm_draft_service: FsmDraftService,
    messenger_client: MessengerClient,
) -> None:
    """Handle Support: save draft if in flow, clear FSM, send support text."""
    if not incoming.user.external_id:
        return
    state_key = await state_store.get_state()
    data = await state_store.get_data()
    flow_type = _flow_type_from_state(state_key)
    if flow_type and data:
        user = await user_role_service.get_user(
            external_id=incoming.user.external_id,
            messenger_type=incoming.user.messenger_type,
        )
        if user is not None:
            await fsm_draft_service.save_draft(
                user_id=user.user_id,
                flow_type=flow_type,
                state_key=state_key or "",
                data=data,
            )

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
        advertiser_menu_keyboard()
        if advertiser is not None
        else main_menu_keyboard()
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=SUPPORT_RESPONSE_TEXT,
        keyboard=reply_markup,
    )
