"""Start and role selection handlers."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType, UserRole


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
    role = UserRole.BLOGGER if message.text == "Я блогер" else UserRole.ADVERTISER

    user_role_service.set_role(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
        role=role,
    )

    if role == UserRole.BLOGGER:
        await message.answer(
            "Role saved. To register as a blogger, send /register.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="/register")]],
                resize_keyboard=True,
            ),
        )
        return

    await message.answer(
        "Role saved. To register as an advertiser, send /register_advertiser.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="/register_advertiser")]],
            resize_keyboard=True,
        ),
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
