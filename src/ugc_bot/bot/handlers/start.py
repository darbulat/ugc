"""Start and role selection handlers."""

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.bot.handlers.keyboards import (
    CHANGE_ROLE_BUTTON_TEXT,
    SUPPORT_BUTTON_TEXT,
    advertiser_menu_keyboard,
    advertiser_start_keyboard,
    creator_filled_profile_keyboard,
    creator_start_keyboard,
    main_menu_keyboard,
)
from ugc_bot.domain.enums import MessengerType

router = Router()

START_TEXT = "UMC — сервис для UGC.\n" "Бизнесу — подбор креаторов, креаторам — заказы."

SUPPORT_RESPONSE_TEXT = (
    "Служба поддержки: @usemycontent\n" "Обращайтесь по любым вопросам!"
)

CREATOR_LABEL = "Я креатор"
ADVERTISER_LABEL = "Мне нужны UGC‑креаторы"

CREATOR_INTRO_TEXT = "Выберите действие:"

CREATOR_INTRO_TEXT_NOT_REGISTERED = (
    "Ты — UGC‑креатор.\n"
    "После регистрации бренды смогут находить тебя и отправлять предложения."
)

ADVERTISER_INTRO_TEXT = (
    "Вы выбрали роль «Мне нужны UGC‑креаторы».\n"
    "Давайте создадим профиль, чтобы вы могли размещать заказы."
)


@router.message(CommandStart())
async def start_command(message: Message, user_role_service: UserRoleService) -> None:
    """Handle the /start command."""

    if message.from_user is None:
        return

    external_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name or "user"

    await user_role_service.set_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
        role_chosen=False,
    )
    await message.answer(START_TEXT, reply_markup=_role_keyboard())


@router.message(Command("role"))
async def role_command(message: Message, state: FSMContext) -> None:
    """Handle the /role command for role switching; clear any in-progress flow."""
    await state.clear()
    await message.answer(START_TEXT, reply_markup=_role_keyboard())


@router.message(lambda msg: msg.text == CHANGE_ROLE_BUTTON_TEXT)
async def change_role_button(message: Message, state: FSMContext) -> None:
    """Handle 'Смена роли' button — show start screen again."""
    await state.clear()
    await message.answer(START_TEXT, reply_markup=_role_keyboard())


@router.message(lambda msg: msg.text in {CREATOR_LABEL, ADVERTISER_LABEL})
async def choose_role(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state: FSMContext,
) -> None:
    """Persist selected role and guide the user."""

    if message.from_user is None:
        return
    await state.clear()
    external_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name or "user"
    text = message.text or ""

    await user_role_service.set_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
        role_chosen=True,
    )

    if text == CREATOR_LABEL:
        user = await user_role_service.get_user(
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM,
        )
        blogger_profile = (
            await profile_service.get_blogger_profile(user.user_id) if user else None
        )
        if blogger_profile is not None:
            await message.answer(
                CREATOR_INTRO_TEXT,
                reply_markup=creator_filled_profile_keyboard(),
            )
        else:
            await message.answer(
                CREATOR_INTRO_TEXT_NOT_REGISTERED,
                reply_markup=creator_start_keyboard(),
            )
        return

    if text == ADVERTISER_LABEL:
        user = await user_role_service.get_user(
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM,
        )
        advertiser_profile = (
            await profile_service.get_advertiser_profile(user.user_id) if user else None
        )
        if advertiser_profile is not None:
            await message.answer(
                CREATOR_INTRO_TEXT,
                reply_markup=advertiser_menu_keyboard(),
            )
        else:
            await message.answer(
                ADVERTISER_INTRO_TEXT,
                reply_markup=advertiser_start_keyboard(),
            )
        return


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
    """Handle Support button: save draft if in a flow, clear FSM, send support text."""

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
    username = message.from_user.username or message.from_user.first_name or "user"

    await user_role_service.set_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
        role_chosen=True,
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
