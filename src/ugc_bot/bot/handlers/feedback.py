"""Handlers for feedback after contacts sharing."""

from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.application.ports import NpsRepository
from ugc_bot.bot.handlers.utils import get_user_and_ensure_allowed_callback


router = Router()

_FEEDBACK_TEXT_MAP = {
    "ok": "✅ Сделка состоялась",
    "no_deal": "❌ Не договорились",
    "postpone": "⏳ Еще не связался",
    "issue": "⚠️ Проблема / подозрение на мошенничество",
}

# No-deal reason keys and labels (blogger: first 4; advertiser: all 5)
_NO_DEAL_REASONS_BLOGGER = [
    ("conditions", "Не сошлись по условиям"),
    ("timing", "Не подошли сроки"),
    ("differed_from_offer", "Условия отличались от оффера"),
    ("other", "Другое"),
]
_NO_DEAL_REASONS_ADVERTISER = _NO_DEAL_REASONS_BLOGGER + [
    ("creator_wanted_to_change", "Креатор хотел изменить условия"),
]


def _no_deal_reason_keyboard(kind: str, interaction_id: UUID) -> InlineKeyboardMarkup:
    """Build inline keyboard for no_deal reason (blogger or advertiser)."""
    reasons = _NO_DEAL_REASONS_ADVERTISER if kind == "adv" else _NO_DEAL_REASONS_BLOGGER
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"feedback_reason:{kind}:{interaction_id}:{key}",
                )
            ]
            for key, label in reasons
        ]
    )


def _nps_keyboard(interaction_id: UUID) -> InlineKeyboardMarkup:
    """Build inline keyboard for NPS 1-5."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(i),
                    callback_data=f"nps:{interaction_id}:{i}",
                )
                for i in range(1, 6)
            ]
        ]
    )


@router.callback_query(lambda c: c.data and c.data.startswith("feedback_reason:"))
async def handle_feedback_reason(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    blogger_registration_service: BloggerRegistrationService,
) -> None:
    """Handle no_deal reason selection: record feedback and optionally mark blogger."""

    if not callback.data:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Неверный формат.")
        return
    _, kind, interaction_id_raw, reason_key = parts
    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await callback.answer("Неверный идентификатор.")
        return

    user = await get_user_and_ensure_allowed_callback(
        callback,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Заблокированные пользователи не могут оставлять отзыв.",
        pause_msg="Пользователи на паузе не могут оставлять отзыв.",
    )
    if user is None:
        return

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

    reason_labels = {k: label for k, label in _NO_DEAL_REASONS_ADVERTISER}
    reason_labels.update({k: label for k, label in _NO_DEAL_REASONS_BLOGGER})
    reason_label = reason_labels.get(reason_key, reason_key)
    feedback_text = "❌ Не договорились: " + reason_label

    if kind == "adv":
        await interaction_service.record_advertiser_feedback(
            interaction_id, feedback_text
        )
        if reason_key == "creator_wanted_to_change":
            await blogger_registration_service.increment_wanted_to_change_terms_count(
                interaction.blogger_id
            )
    else:
        await interaction_service.record_blogger_feedback(interaction_id, feedback_text)

    await callback.answer("Спасибо, ответ сохранен.")
    if callback.message:
        await callback.message.answer("Спасибо за обратную связь.")


@router.callback_query(lambda c: c.data and c.data.startswith("nps:"))
async def handle_nps(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    nps_repo: NpsRepository,
) -> None:
    """Handle NPS score selection (1-5) after advertiser ok."""

    if not callback.data:
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Неверный формат.")
        return
    _, interaction_id_raw, score_raw = parts
    try:
        interaction_id = UUID(interaction_id_raw)
        score = int(score_raw)
    except (ValueError, TypeError):
        await callback.answer("Неверный формат.")
        return
    if score < 1 or score > 5:
        await callback.answer("Оценка должна быть от 1 до 5.")
        return

    user = await get_user_and_ensure_allowed_callback(
        callback,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Заблокированные пользователи не могут оценивать.",
        pause_msg="Пользователи на паузе не могут оценивать.",
    )
    if user is None:
        return

    await nps_repo.save(interaction_id, score)
    await callback.answer("Спасибо за оценку!")


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("feedback:")
)
async def handle_feedback(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    nps_repo: NpsRepository,
) -> None:
    """Handle feedback callbacks from advertiser or blogger."""

    if not callback.data:
        return

    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Неверный формат ответа.")
        return

    _, kind, interaction_id_raw, status_raw = parts

    if status_raw == "no_deal":
        try:
            interaction_id = UUID(interaction_id_raw)
        except ValueError:
            await callback.answer("Неверный идентификатор.")
            return
        user = await get_user_and_ensure_allowed_callback(
            callback,
            user_role_service,
            user_not_found_msg="Пользователь не найден.",
            blocked_msg="Заблокированные пользователи не могут оставлять отзыв.",
            pause_msg="Пользователи на паузе не могут оставлять отзыв.",
        )
        if user is None:
            return
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
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "По какой причине не удалось договориться?",
                reply_markup=_no_deal_reason_keyboard(kind, interaction_id),
            )
        return

    feedback_text = _FEEDBACK_TEXT_MAP.get(status_raw)
    if feedback_text is None:
        await callback.answer("Неверный статус.")
        return

    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await callback.answer("Неверный идентификатор.")
        return

    user = await get_user_and_ensure_allowed_callback(
        callback,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Заблокированные пользователи не могут оставлять отзыв.",
        pause_msg="Пользователи на паузе не могут оставлять отзыв.",
    )
    if user is None:
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

        if status_raw == "postpone":
            if (
                updated_interaction.postpone_count
                >= interaction_service.max_postpone_count
            ):
                await callback.answer(
                    "Достигнут максимум переносов. Статус зафиксирован как 'Не договорились'."
                )
                if callback.message:
                    await callback.message.answer("Спасибо за обратную связь.")
            else:
                await callback.answer(
                    f"Проверка перенесена на 72 часа. "
                    f"Переносов: {updated_interaction.postpone_count}/{interaction_service.max_postpone_count}"
                )
                if callback.message:
                    if kind == "blog":
                        await callback.message.answer(
                            "Хорошо, вернёмся к этому позже. "
                            "Если заказчик напишет — просто ответьте ему."
                        )
                    else:
                        await callback.message.answer(
                            "Поняли, вернёмся к этому позже. "
                            "Креатор не видит ваши контакты, связь начинается с вашей стороны."
                        )
        elif status_raw == "ok":
            await callback.answer("Спасибо, ответ сохранен.")
            if callback.message:
                if kind == "blog":
                    await callback.message.answer(
                        "Спасибо за обратную связь. Если понадобится помощь — мы на связи."
                    )
                else:
                    await callback.message.answer(
                        "Спасибо за обратную связь. Желаем удачной работы с креатором."
                    )
                    await callback.message.answer(
                        "Оцените, пожалуйста, удобство работы с платформой UMC:",
                        reply_markup=_nps_keyboard(interaction_id),
                    )
        elif status_raw == "issue":
            await callback.answer("Спасибо, ответ сохранен.")
            if callback.message:
                await callback.message.answer(
                    "Мы приняли вашу заявку. Опишите проблему и приложите скриншоты — "
                    "поддержка свяжется с вами. Или нажмите «Поддержка» в меню."
                )
        else:
            await callback.answer("Спасибо, ответ сохранен.")
    except Exception:
        await callback.answer("Произошла ошибка. Попробуйте позже.")
        return
