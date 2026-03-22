"""Handlers for admin sending messages to users via the bot (command /write)."""

import logging
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import resolve_messenger_dependencies

logger = logging.getLogger(__name__)

router = Router()

WRITE_CMD = "write"
CANCEL_CMD = "cancel"

PROMPT_USER_ID = (
    "Введите ID пользователя (UUID), которому отправить сообщение. "
    "ID можно взять в карточке пользователя в админке.\n"
    "Отмена: /cancel"
)
PROMPT_TEXT = "Введите текст сообщения. Отмена: /cancel"
SENT_OK = "Сообщение отправлено."
CANCELLED = "Отправка отменена."
ACCESS_DENIED = "Доступ запрещён. Команда только для администраторов."
USER_NOT_FOUND = "Пользователь не найден."
USER_NOT_TELEGRAM = (
    "Отправка только пользователям Telegram. "
    "У этого пользователя другой мессенджер."
)
INVALID_UUID = (
    "Неверный формат UUID. Введите ID пользователя (например из админки)."
)


class AdminWriteStates(StatesGroup):
    """FSM states for admin write-to-user flow."""

    waiting_user_id = State()
    waiting_text = State()


async def _require_admin(
    message: Message,
    event_adapter: MessengerEventAdapter,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None,
) -> bool:
    """True if current user is admin; else send access denied, return False."""
    incoming = event_adapter.from_message(message)
    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    if user is None or not user.admin:
        text = ACCESS_DENIED
        if messenger_client:
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=text,
            )
        else:
            await message.answer(text)
        return False
    return True


def _parse_uuid(value: str | None) -> UUID | None:
    """Parse string as UUID. Return None if invalid."""
    if not value or not value.strip():
        return None
    raw = value.strip()
    if len(raw) != 32 and "-" not in raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


@router.message(Command(WRITE_CMD))
async def cmd_write(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start admin write flow: ask for user ID (admin-only)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    if not await _require_admin(
        message, event_adapter, user_role_service, messenger_client
    ):
        return
    await state.set_state(AdminWriteStates.waiting_user_id)
    await state.set_data({})
    await messenger_client.send_text(
        chat_id=event_adapter.from_message(message).chat_id,
        text=PROMPT_USER_ID,
    )


@router.message(Command(CANCEL_CMD), AdminWriteStates.waiting_user_id)
@router.message(Command(CANCEL_CMD), AdminWriteStates.waiting_text)
async def cmd_cancel_write(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Cancel write flow from any step."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    await state.clear()
    chat_id = event_adapter.from_message(message).chat_id
    await messenger_client.send_text(chat_id=chat_id, text=CANCELLED)


@router.message(AdminWriteStates.waiting_user_id)
async def step_user_id(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Accept user UUID, validate, then ask for message text."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    if not await _require_admin(
        message, event_adapter, user_role_service, messenger_client
    ):
        return
    chat_id = event_adapter.from_message(message).chat_id
    user_id = _parse_uuid(message.text)
    if user_id is None:
        await messenger_client.send_text(
            chat_id=chat_id,
            text=INVALID_UUID,
        )
        return
    target = await user_role_service.get_user_by_id(user_id)
    if target is None:
        await messenger_client.send_text(
            chat_id=chat_id,
            text=USER_NOT_FOUND,
        )
        return
    if not target.telegram_id:
        await messenger_client.send_text(
            chat_id=chat_id,
            text=USER_NOT_TELEGRAM,
        )
        return
    await state.update_data(target_user_id=str(target.user_id))
    await state.set_state(AdminWriteStates.waiting_text)
    await messenger_client.send_text(
        chat_id=chat_id,
        text=PROMPT_TEXT,
    )


@router.message(AdminWriteStates.waiting_text)
async def step_text(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Send message to target user and clear state."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    if not await _require_admin(
        message, event_adapter, user_role_service, messenger_client
    ):
        return
    chat_id = event_adapter.from_message(message).chat_id
    data = await state.get_data()
    target_user_id_str = data.get("target_user_id")
    if not target_user_id_str:
        await state.clear()
        await messenger_client.send_text(
            chat_id=chat_id,
            text=USER_NOT_FOUND,
        )
        return
    try:
        target_user_id = UUID(target_user_id_str)
    except ValueError:
        await state.clear()
        await messenger_client.send_text(
            chat_id=chat_id,
            text=USER_NOT_FOUND,
        )
        return
    target = await user_role_service.get_user_by_id(target_user_id)
    if target is None:
        await state.clear()
        await messenger_client.send_text(
            chat_id=chat_id,
            text=USER_NOT_FOUND,
        )
        return
    if not target.telegram_id:
        await state.clear()
        await messenger_client.send_text(
            chat_id=chat_id,
            text=USER_NOT_TELEGRAM,
        )
        return
    text_to_send = (message.text or "").strip()
    if not text_to_send:
        await messenger_client.send_text(
            chat_id=chat_id,
            text=PROMPT_TEXT,
        )
        return
    try:
        await messenger_client.send_text(
            chat_id=target.telegram_id,
            text=text_to_send,
        )
        logger.info(
            "Admin sent message to user",
            extra={
                "target_user_id": str(target.user_id),
                "admin_chat_id": chat_id,
            },
        )
    except Exception as exc:
        logger.warning(
            "Failed to send admin message to user",
            extra={
                "target_user_id": str(target.user_id),
                "error": str(exc),
            },
        )
        await messenger_client.send_text(
            chat_id=chat_id,
            text=f"Ошибка отправки: {exc!s}",
        )
        return
    await state.clear()
    await messenger_client.send_text(chat_id=chat_id, text=SENT_OK)
