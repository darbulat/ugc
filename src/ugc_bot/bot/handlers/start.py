"""Start and role selection handlers."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    CHANGE_ROLE_BUTTON_TEXT,
    SUPPORT_BUTTON_TEXT,
    main_menu_keyboard,
)
from ugc_bot.domain.enums import MessengerType

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
    message: Message, user_role_service: UserRoleService
) -> None:
    """Handle the /start command."""

    if message.from_user is None:
        return

    external_id = str(message.from_user.id)
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
    )
    username = user.username if user else ""

    await user_role_service.set_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
        role_chosen=False,
        telegram_username=message.from_user.username,
    )
    await message.answer(START_TEXT, reply_markup=_role_keyboard())


@router.message(Command("role"))
@router.message(lambda msg: msg.text == CHANGE_ROLE_BUTTON_TEXT)
async def change_role_button(message: Message, state: FSMContext) -> None:
    """Handle /role and 'Смена роли' — show start screen again."""
    await state.clear()
    await message.answer(START_TEXT, reply_markup=_role_keyboard())


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


@router.message(lambda msg: (msg.text or "").strip() == SUPPORT_BUTTON_TEXT)
async def support_button(
    message: Message,
    user_role_service: UserRoleService,
    state: FSMContext,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Handle Support: save draft if in flow, clear FSM, send support text."""

    if message.from_user is None:
        return

    state_key = await state.get_state()
    data = await state.get_data()
    flow_type = _flow_type_from_state(state_key)
    if flow_type and data:
        user = await user_role_service.get_user(
            external_id=str(message.from_user.id),
            messenger_type=MessengerType.TELEGRAM,
        )
        if user is not None:
            await fsm_draft_service.save_draft(
                user_id=user.user_id,
                flow_type=flow_type,
                state_key=state_key or "",
                data=data,
            )

    await state.clear()

    external_id = str(message.from_user.id)
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
    )
    username = user.username if user else ""

    await user_role_service.set_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
        role_chosen=True,
        telegram_username=message.from_user.username,
    )
    await message.answer(
        SUPPORT_RESPONSE_TEXT,
        reply_markup=main_menu_keyboard(),
    )


def _role_keyboard() -> ReplyKeyboardMarkup:
    """Build a reply keyboard for role selection."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CREATOR_LABEL)],
            [KeyboardButton(text=ADVERTISER_LABEL)],
            [KeyboardButton(text=SUPPORT_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
