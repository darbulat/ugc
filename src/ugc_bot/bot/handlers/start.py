"""Start and role selection handlers."""

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    CHANGE_ROLE_BUTTON_TEXT,
    SUPPORT_BUTTON_TEXT,
    advertiser_start_keyboard,
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

CREATOR_INTRO_TEXT = (
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
async def role_command(message: Message) -> None:
    """Handle the /role command for role switching."""

    await message.answer(START_TEXT, reply_markup=_role_keyboard())


@router.message(lambda msg: msg.text == CHANGE_ROLE_BUTTON_TEXT)
async def change_role_button(message: Message) -> None:
    """Handle 'Смена роли' button — show start screen again."""

    await message.answer(START_TEXT, reply_markup=_role_keyboard())


@router.message(lambda msg: msg.text in {CREATOR_LABEL, ADVERTISER_LABEL})
async def choose_role(message: Message, user_role_service: UserRoleService) -> None:
    """Persist selected role and guide the user."""

    if message.from_user is None:
        return

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
        await message.answer(
            CREATOR_INTRO_TEXT,
            reply_markup=creator_start_keyboard(),
        )
        return

    if text == ADVERTISER_LABEL:
        await message.answer(
            ADVERTISER_INTRO_TEXT,
            reply_markup=advertiser_start_keyboard(),
        )
        return


@router.message(lambda msg: (msg.text or "").strip() == SUPPORT_BUTTON_TEXT)
async def support_button(
    message: Message,
    user_role_service: UserRoleService,
    state: FSMContext,
) -> None:
    """Handle Support button: clear FSM if needed, send support text, mark role chosen."""

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
