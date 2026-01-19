"""Start and role selection handlers."""

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import advertiser_menu_keyboard
from ugc_bot.domain.enums import MessengerType


router = Router()


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    """Handle the /start command."""

    user_name = message.from_user.first_name if message.from_user else "there"
    response_text = (
        f"Hi {user_name}! Choose your role:\n" "• Я блогер\n" "• Я рекламодатель"
    )
    await message.answer(response_text, reply_markup=_role_keyboard())


@router.message(Command("role"))
async def role_command(message: Message) -> None:
    """Handle the /role command for role switching."""

    await message.answer("Choose your role:", reply_markup=_role_keyboard())


@router.message(lambda msg: msg.text in {"Я блогер", "Я рекламодатель"})
async def choose_role(message: Message, user_role_service: UserRoleService) -> None:
    """Persist selected role and guide the user."""

    if message.from_user is None:
        return

    external_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name or "user"
    is_blogger = message.text == "Я блогер"
    user_role_service.set_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
    )

    if is_blogger:
        await message.answer(
            "Role saved. To register as a blogger, send /register.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="/register")],
                    [KeyboardButton(text="Мой профиль")],
                ],
                resize_keyboard=True,
            ),
        )
        return

    await message.answer(
        "Role saved. To register as an advertiser, send /register_advertiser.",
        reply_markup=advertiser_menu_keyboard(),
    )


def _role_keyboard() -> ReplyKeyboardMarkup:
    """Build a reply keyboard for role selection."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Я блогер")],
            [KeyboardButton(text="Я рекламодатель")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
