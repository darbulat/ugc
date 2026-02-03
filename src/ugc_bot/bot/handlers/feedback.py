"""Handlers for feedback after contacts sharing."""

from uuid import UUID

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.application.ports import NpsRepository
from ugc_bot.bot.handlers.utils import get_user_and_ensure_allowed_callback
from ugc_bot.domain.enums import MessengerType


router = Router()


class FeedbackStates(StatesGroup):
    """FSM states for feedback follow-up (no_deal other text, issue description)."""

    waiting_no_deal_other = State()
    waiting_issue_description = State()


_FEEDBACK_TEXT_MAP = {
    "ok": "✅ Всё прошло нормально",
    "no_deal": "❌ Не договорились",
    "postpone": "⏳ Ещё не связался",
    "issue": "⚠️ Проблема / подозрение на мошенничество",
}

# No-deal reason keys and labels (blogger: 4; advertiser: 4, different third option)
_NO_DEAL_REASONS_BLOGGER = [
    ("conditions", "💰 Не сошлись по условиям"),
    ("timing", "⏱ Не подошли сроки"),
    ("differed_from_offer", "📝 Условия отличались от оффера"),
    ("other", "🤝 Другое"),
]
_NO_DEAL_REASONS_ADVERTISER = [
    ("conditions", "💰 Не сошлись по условиям"),
    ("timing", "⏱ Не подошли сроки"),
    ("creator_wanted_to_change", "📝 Креатор хотел изменить условия"),
    ("other", "🤝 Другое"),
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
    """Build inline keyboard for NPS 1-5 (star emoji labels)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"⭐️ {i}",
                    callback_data=f"nps:{interaction_id}:{i}",
                )
                for i in range(1, 6)
            ]
        ]
    )


@router.callback_query(lambda c: c.data and c.data.startswith("feedback_reason:"))
async def handle_feedback_reason(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    blogger_registration_service: BloggerRegistrationService,
) -> None:
    """Handle no_deal reason selection: record feedback or ask for text (Другое)."""

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

    if reason_key == "other":
        await state.set_state(FeedbackStates.waiting_no_deal_other)
        await state.update_data(
            feedback_interaction_id=str(interaction_id),
            feedback_kind=kind,
        )
        await callback.answer()
        if callback.message:
            await callback.message.answer("Напишите, пожалуйста, причину:")
        return

    reason_labels = {k: label for k, label in _NO_DEAL_REASONS_BLOGGER}
    reason_labels.update({k: label for k, label in _NO_DEAL_REASONS_ADVERTISER})
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


@router.message(FeedbackStates.waiting_no_deal_other)
async def handle_no_deal_other_text(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
) -> None:
    """Handle free-text reason for no_deal 'Другое': record feedback and clear state."""

    if message.from_user is None:
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Введите причину текстом.")
        return

    user = await user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await state.clear()
        return

    data = await state.get_data()
    await state.clear()
    interaction_id_raw = data.get("feedback_interaction_id")
    kind = data.get("feedback_kind")
    if not interaction_id_raw or kind not in ("adv", "blog"):
        await message.answer("Сессия истекла. Ответьте на вопрос обратной связи снова.")
        return

    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await message.answer("Ошибка. Попробуйте снова.")
        return

    interaction = await interaction_service.get_interaction(interaction_id)
    if interaction is None:
        await message.answer("Взаимодействие не найдено.")
        return
    if kind == "adv" and interaction.advertiser_id != user.user_id:
        await message.answer("Недостаточно прав.")
        return
    if kind == "blog" and interaction.blogger_id != user.user_id:
        await message.answer("Недостаточно прав.")
        return

    feedback_text = "❌ Не договорились: Другое: " + text
    if kind == "adv":
        await interaction_service.record_advertiser_feedback(
            interaction_id, feedback_text
        )
    else:
        await interaction_service.record_blogger_feedback(interaction_id, feedback_text)
    await message.answer("Спасибо за обратную связь.")


@router.message(FeedbackStates.waiting_issue_description)
async def handle_issue_description(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    complaint_service: ComplaintService,
) -> None:
    """Handle issue description and optional photos: create complaint, record ISSUE."""

    if message.from_user is None:
        return
    text = (message.text or message.caption or "").strip() or "Без описания"

    user = await user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await state.clear()
        return

    data = await state.get_data()
    interaction_id_raw = data.get("feedback_interaction_id")
    kind = data.get("feedback_kind")
    if not interaction_id_raw or kind not in ("adv", "blog"):
        await state.clear()
        await message.answer("Сессия истекла. Ответьте на вопрос обратной связи снова.")
        return

    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await state.clear()
        await message.answer("Ошибка. Попробуйте снова.")
        return

    interaction = await interaction_service.get_interaction(interaction_id)
    if interaction is None:
        await state.clear()
        await message.answer("Взаимодействие не найдено.")
        return
    if kind == "adv" and interaction.advertiser_id != user.user_id:
        await state.clear()
        await message.answer("Недостаточно прав.")
        return
    if kind == "blog" and interaction.blogger_id != user.user_id:
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    reporter_id = user.user_id
    reported_id = interaction.blogger_id if kind == "adv" else interaction.advertiser_id
    reason = text + " [из фидбека: проблема/мошенничество]"
    try:
        await complaint_service.create_complaint(
            reporter_id=reporter_id,
            reported_id=reported_id,
            order_id=interaction.order_id,
            reason=reason,
        )
    except Exception:
        pass

    feedback_text = "⚠️ Проблема / подозрение на мошенничество"
    if kind == "adv":
        await interaction_service.record_advertiser_feedback(
            interaction_id, feedback_text
        )
    else:
        await interaction_service.record_blogger_feedback(interaction_id, feedback_text)
    await state.clear()
    await message.answer(
        "Мы приняли вашу заявку. Поддержка разберётся в ситуации. "
        "При необходимости нажмите «Поддержка» в меню."
    )


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
    state: FSMContext,
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
            question = (
                "Подскажите, пожалуйста, по какой причине не удалось договориться?"
                if kind == "blog"
                else "По какой причине не удалось договориться?"
            )
            await callback.message.answer(
                question,
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

        if status_raw == "issue":
            await state.set_state(FeedbackStates.waiting_issue_description)
            await state.update_data(
                feedback_interaction_id=str(interaction_id),
                feedback_kind=kind,
            )
            await callback.answer("Спасибо.")
            if callback.message:
                await callback.message.answer(
                    "Опишите, пожалуйста, проблему и приложите скриншоты переписки или "
                    "другие подтверждения. Это поможет нам разобраться в ситуации и принять меры.\n"
                    "👉 Напишите текст ниже и при необходимости прикрепите скриншоты."
                )
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
                            "Хорошо, вернёмся к этому позже 👍 "
                            "Если заказчик напишет — просто ответьте ему."
                        )
                    else:
                        await callback.message.answer(
                            "Поняли, вернёмся к этому позже 👍\n"
                            "ℹ️ Напоминаем: креатор не видит ваши контакты и не может "
                            "написать первым. Связь всегда начинается с вашей стороны."
                        )
        elif status_raw == "ok":
            await callback.answer("Спасибо, ответ сохранен.")
            if callback.message:
                if kind == "blog":
                    await callback.message.answer(
                        "Спасибо за обратную связь 👍 "
                        "Если понадобится помощь — мы на связи."
                    )
                else:
                    await callback.message.answer(
                        "Спасибо за обратную связь 👍 "
                        "Желаем удачной работы с креатором."
                    )
                    await callback.message.answer(
                        "Оцените, пожалуйста, удобство работы с платформой UMC:",
                        reply_markup=_nps_keyboard(interaction_id),
                    )
        else:
            await callback.answer("Спасибо, ответ сохранен.")
    except Exception:
        await callback.answer("Произошла ошибка. Попробуйте позже.")
        return
