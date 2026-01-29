"""Handlers for feedback after contacts sharing."""

from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType


router = Router()

_FEEDBACK_TEXT_MAP = {
    "ok": "✅ Сделка состоялась",
    "no_deal": "❌ Не договорились",
    "postpone": "⏳ Еще не связался",
    "issue": "⚠️ Проблема / подозрение на мошенничество",
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
    feedback_text = _FEEDBACK_TEXT_MAP.get(status_raw)
    if feedback_text is None:
        await callback.answer("Неверный статус.")
        return

    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await callback.answer("Неверный идентификатор.")
        return

    user = await user_role_service.get_user(
        external_id=str(callback.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await callback.answer("Пользователь не найден.")
        return

    try:
        interaction = await interaction_service.get_interaction(interaction_id)
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
            updated_interaction = await interaction_service.record_advertiser_feedback(
                interaction_id, feedback_text
            )
        else:
            updated_interaction = await interaction_service.record_blogger_feedback(
                interaction_id, feedback_text
            )

        # Provide feedback based on action
        if status_raw == "postpone":
            if (
                updated_interaction.postpone_count
                >= interaction_service.max_postpone_count
            ):
                await callback.answer(
                    "Достигнут максимум переносов. Статус зафиксирован как 'Не договорились'."
                )
            else:
                await callback.answer(
                    f"Проверка перенесена на 72 часа. "
                    f"Переносов использовано: {updated_interaction.postpone_count}/{interaction_service.max_postpone_count}"
                )
        else:
            await callback.answer("Спасибо, ответ сохранен.")
    except Exception:
        await callback.answer("Произошла ошибка. Попробуйте позже.")
        return
