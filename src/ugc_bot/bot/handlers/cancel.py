"""Cancel input handlers."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from ugc_bot.bot.handlers.keyboards import cancel_keyboard


router = Router()


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    """Handle /cancel command for any state."""

    await _cancel_flow(message, state)


@router.message(lambda msg: (msg.text or "").strip() == "Отменить")
async def cancel_button(message: Message, state: FSMContext) -> None:
    """Handle cancel button for any state."""

    await _cancel_flow(message, state)


async def _cancel_flow(message: Message, state: FSMContext) -> None:
    """Clear FSM state and notify user."""

    if await state.get_state() is None:
        await message.answer(
            "Нечего отменять.",
            reply_markup=cancel_keyboard(),
        )
        return

    await state.clear()
    await message.answer(
        "Ввод отменен. Вы можете начать заново командой /start или /role.",
        reply_markup=ReplyKeyboardRemove(),
    )
