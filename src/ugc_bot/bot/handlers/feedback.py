"""Handlers for feedback after contacts sharing."""

from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import InteractionStatus, MessengerType


router = Router()

_STATUS_MAP = {
    "ok": InteractionStatus.OK,
    "no_deal": InteractionStatus.NO_DEAL,
    "issue": InteractionStatus.ISSUE,
}


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("feedback:")
)
async def handle_feedback(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
) -> None:
    """Handle feedback callbacks from advertiser or blogger."""

    if callback.from_user is None or not callback.data:
        return

    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Неверный формат ответа.")
        return

    _, kind, interaction_id_raw, status_raw = parts
    status = _STATUS_MAP.get(status_raw)
    if status is None:
        await callback.answer("Неверный статус.")
        return

    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await callback.answer("Неверный идентификатор.")
        return

    user = user_role_service.get_user(
        external_id=str(callback.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await callback.answer("Пользователь не найден.")
        return

    try:
        interaction = interaction_service.interaction_repo.get_by_id(interaction_id)
        if interaction is None:
            await callback.answer("Взаимодействие не найдено.")
            return

        if kind == "adv" and interaction.advertiser_id != user.user_id:
            await callback.answer("Недостаточно прав.")
            return
        if kind == "blog" and interaction.blogger_id != user.user_id:
            await callback.answer("Недостаточно прав.")
            return

        if kind == "adv":
            interaction_service.record_advertiser_feedback(interaction_id, status)
        else:
            interaction_service.record_blogger_feedback(interaction_id, status)
    except Exception:
        await callback.answer("Произошла ошибка. Попробуйте позже.")
        return

    await callback.answer("Спасибо, ответ сохранен.")
