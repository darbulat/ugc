"""Handlers for messenger-choice survey broadcast."""

import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.nps_service import NpsService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    CALLBACK_SURVEY_MESSENGER_MAX,
    CALLBACK_SURVEY_MESSENGER_OTHER,
    CALLBACK_SURVEY_MESSENGER_TG,
)
from ugc_bot.bot.handlers.utils import resolve_messenger_dependencies
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType

logger = logging.getLogger(__name__)

router = Router()

_THANK_YOU = "Спасибо за ответ! 🙌"
_PROMPT_OTHER = "Напишите, какой мессенджер вы предпочтёте:"


class SurveyMessengerStates(StatesGroup):
    waiting_other_text = State()


async def _get_user(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    messenger_client: "MessengerClient | None",
    event_adapter: "MessengerEventAdapter | None",
) -> User | None:
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    if not incoming.user.external_id:
        return None
    return await user_role_service.get_user(
        incoming.user.external_id, MessengerType.TELEGRAM
    )


async def _remove_inline_keyboard(callback: CallbackQuery) -> None:
    if callback.message:
        edit = getattr(callback.message, "edit_reply_markup", None)
        if callable(edit):
            await edit(reply_markup=None)


@router.callback_query(F.data == CALLBACK_SURVEY_MESSENGER_TG)
async def on_survey_telegram(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    nps_service: NpsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    user = await _get_user(
        callback, user_role_service, messenger_client, event_adapter
    )
    if user is None:
        await callback.answer()
        return
    await nps_service.save(user.user_id, score=0, comment="telegram")
    await _remove_inline_keyboard(callback)
    await callback.answer(_THANK_YOU)


@router.callback_query(F.data == CALLBACK_SURVEY_MESSENGER_MAX)
async def on_survey_max(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    nps_service: NpsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    user = await _get_user(
        callback, user_role_service, messenger_client, event_adapter
    )
    if user is None:
        await callback.answer()
        return
    await nps_service.save(user.user_id, score=0, comment="MAX")
    await _remove_inline_keyboard(callback)
    await callback.answer(_THANK_YOU)


@router.callback_query(F.data == CALLBACK_SURVEY_MESSENGER_OTHER)
async def on_survey_other(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    user = await _get_user(
        callback, user_role_service, messenger_client, event_adapter
    )
    if user is None:
        await callback.answer()
        return
    await state.set_state(SurveyMessengerStates.waiting_other_text)
    await state.update_data(survey_user_id=str(user.user_id))
    await _remove_inline_keyboard(callback)
    await callback.answer()
    if callback.message:
        await callback.message.answer(_PROMPT_OTHER)


@router.message(SurveyMessengerStates.waiting_other_text)
async def on_survey_other_text(
    message: Message,
    state: FSMContext,
    nps_service: NpsService,
) -> None:
    data = await state.get_data()
    user_id_raw = data.get("survey_user_id")
    if not user_id_raw:
        await state.clear()
        return
    user_id = UUID(user_id_raw)
    text = (message.text or "").strip() or None
    await nps_service.save(user_id, score=0, comment=text)
    await state.clear()
    await message.answer(_THANK_YOU)
