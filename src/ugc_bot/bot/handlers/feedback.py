"""Handlers for feedback after contacts sharing."""

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from aiogram import Router

if TYPE_CHECKING:
    from ugc_bot.domain.entities import Interaction, User
    from ugc_bot.infrastructure.redis_lock import IssueDescriptionLockManager
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_complaint,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.application.services.nps_service import NpsService
from ugc_bot.bot.handlers.utils import get_user_and_ensure_allowed_callback
from ugc_bot.domain.enums import MessengerType


router = Router()
logger = logging.getLogger(__name__)


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
# Short codes for callback_data (Telegram limit 64 bytes)
_NO_DEAL_REASONS_BLOGGER = [
    ("conditions", "💰 Не сошлись по условиям", "c"),
    ("timing", "⏱ Не подошли сроки", "t"),
    ("differed_from_offer", "📝 Условия отличались от оффера", "d"),
    ("other", "🤝 Другое", "o"),
]
_NO_DEAL_REASONS_ADVERTISER = [
    ("conditions", "💰 Не сошлись по условиям", "c"),
    ("timing", "⏱ Не подошли сроки", "t"),
    ("creator_wanted_to_change", "📝 Креатор хотел изменить условия", "w"),
    ("other", "🤝 Другое", "o"),
]
_REASON_CODE_TO_KEY = {
    "c": "conditions",
    "t": "timing",
    "d": "differed_from_offer",
    "w": "creator_wanted_to_change",
    "o": "other",
}


def _uuid_hex(uuid_val: UUID) -> str:
    """Return UUID as 32-char hex (no dashes) for compact callback_data."""
    return uuid_val.hex


async def _remove_inline_keyboard(callback: CallbackQuery) -> None:
    """Remove inline keyboard from message after user selection."""
    if callback.message:
        edit_reply_markup = getattr(callback.message, "edit_reply_markup", None)
        if callable(edit_reply_markup):
            await edit_reply_markup(reply_markup=None)


def _parse_uuid_hex(hex_str: str) -> UUID:
    """Parse 32-char hex string to UUID."""
    return UUID(hex=hex_str)


def _no_deal_reason_keyboard(kind: str, interaction_id: UUID) -> InlineKeyboardMarkup:
    """Build inline keyboard for no_deal reason (blogger or advertiser)."""
    reasons = _NO_DEAL_REASONS_ADVERTISER if kind == "adv" else _NO_DEAL_REASONS_BLOGGER
    id_hex = _uuid_hex(interaction_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"fb_r:{kind}:{id_hex}:{code}",
                )
            ]
            for key, label, code in reasons
        ]
    )


_ISSUE_SEND_BUTTON_TEXT = "📤 Отправить"


def _issue_send_keyboard() -> ReplyKeyboardMarkup:
    """Build reply keyboard with 'Отправить' button for issue submission."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=_ISSUE_SEND_BUTTON_TEXT)]],
        resize_keyboard=True,
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


@router.callback_query(lambda c: c.data and c.data.startswith("fb_r:"))
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
    _, kind, interaction_id_raw, reason_code = parts
    try:
        interaction_id = _parse_uuid_hex(interaction_id_raw)
    except (ValueError, TypeError):
        await callback.answer("Неверный идентификатор.")
        return
    reason_key = _REASON_CODE_TO_KEY.get(reason_code)
    if reason_key is None:
        await callback.answer("Неверный формат.")
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
        await _remove_inline_keyboard(callback)
        await callback.answer()
        if callback.message:
            await callback.message.answer("Напишите, пожалуйста, причину:")
        return

    reason_labels = {k: label for k, label, _ in _NO_DEAL_REASONS_BLOGGER}
    reason_labels.update({k: label for k, label, _ in _NO_DEAL_REASONS_ADVERTISER})
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

    await _remove_inline_keyboard(callback)
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
    issue_lock_manager: "IssueDescriptionLockManager",
) -> None:
    """Collect issue description and photos; complaint created on 'Отправить' button."""

    if message.from_user is None:
        return
    text = (message.text or message.caption or "").strip()
    photos = getattr(message, "photo", None)
    # Telegram sends multiple sizes (smallest to largest); take the largest only
    new_file_ids = [photos[-1].file_id] if photos else []

    data = await state.get_data()
    interaction_id_raw = data.get("feedback_interaction_id")
    kind = data.get("feedback_kind")
    if not interaction_id_raw or kind not in ("adv", "blog"):
        await state.clear()
        await message.answer("Сессия истекла. Ответьте на вопрос обратной связи снова.")
        return

    if text == _ISSUE_SEND_BUTTON_TEXT:
        try:
            interaction_id = UUID(interaction_id_raw)
        except ValueError:
            await state.clear()
            await message.answer("Ошибка. Попробуйте снова.")
            return
        user = await user_role_service.get_user(
            external_id=str(message.from_user.id),
            messenger_type=MessengerType.TELEGRAM,
        )
        if user is None:
            await state.clear()
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
        await _create_complaint_from_issue(
            message,
            state,
            interaction_id,
            kind,
            user,
            interaction,
            user_role_service,
            interaction_service,
            complaint_service,
        )
        return

    if not text and not new_file_ids:
        try:
            interaction_id = UUID(interaction_id_raw)
            await message.answer(
                "Добавьте описание или фото, затем нажмите «Отправить».",
                reply_markup=_issue_send_keyboard(),
            )
        except ValueError:
            await message.answer(
                "Добавьте описание или фото, затем нажмите «Отправить»."
            )
        return

    user = await user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await state.clear()
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

    user_key = str(message.from_user.id)
    async with issue_lock_manager.lock(user_key):
        # Re-read state so we see updates from other parallel messages (e.g. media group)
        data = await state.get_data()
        parts = list(data.get("issue_description_parts") or [])
        file_ids = list(data.get("issue_file_ids") or [])

        if text:
            parts.append(text)
        file_ids.extend(new_file_ids)

        await state.update_data(
            issue_description_parts=parts,
            issue_file_ids=file_ids,
        )

    await message.answer(
        "\u200b",
        reply_markup=_issue_send_keyboard(),
    )


async def _create_complaint_from_issue(
    message: Message,
    state: FSMContext,
    interaction_id: UUID,
    kind: str,
    user: "User",
    interaction: "Interaction",
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    complaint_service: ComplaintService,
) -> bool:
    """Create complaint from collected issue data. Returns True on success."""

    data = await state.get_data()
    parts_list = data.get("issue_description_parts") or []
    file_ids = data.get("issue_file_ids") or []

    if not parts_list and not file_ids:
        await message.answer(
            "Добавьте описание или фото перед отправкой.",
            reply_markup=_issue_send_keyboard(),
        )
        return False

    reason = "\n\n".join(parts_list) if parts_list else "Без описания"
    reason += " [из фидбека: проблема/мошенничество]"

    reporter_id = user.user_id
    reported_id = interaction.blogger_id if kind == "adv" else interaction.advertiser_id

    try:
        complaint = await complaint_service.create_complaint(
            reporter_id=reporter_id,
            reported_id=reported_id,
            order_id=interaction.order_id,
            reason=reason,
            file_ids=file_ids if file_ids else None,
        )
        if message.bot:
            await notify_admins_about_complaint(
                complaint, message.bot, user_role_service
            )
    except Exception as exc:
        logger.exception(
            "Failed to create complaint from feedback",
            extra={
                "interaction_id": str(interaction_id),
                "reporter_id": str(reporter_id),
                "order_id": str(interaction.order_id),
                "error": str(exc),
            },
        )
        await state.clear()
        await message.answer(
            "Произошла ошибка при создании заявки. Пожалуйста, попробуйте снова "
            "или обратитесь в поддержку через меню.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return False

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
        "При необходимости нажмите «Поддержка» в меню.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return True


@router.callback_query(lambda c: c.data and c.data.startswith("nps:"))
async def handle_nps(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    nps_service: NpsService,
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

    interaction = await interaction_service.get_interaction(interaction_id)
    if interaction is None:
        await callback.answer("Взаимодействие не найдено.")
        return
    if interaction.advertiser_id != user.user_id:
        await callback.answer("Недостаточно прав.")
        return

    await nps_service.save(interaction_id, score)
    await callback.answer("Спасибо за оценку!")
    if callback.message:
        edit_reply_markup = getattr(callback.message, "edit_reply_markup", None)
        if callable(edit_reply_markup):
            await edit_reply_markup(reply_markup=None)


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("feedback:")
)
async def handle_feedback(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    nps_service: NpsService,
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
        await _remove_inline_keyboard(callback)
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
                issue_description_parts=[],
                issue_file_ids=[],
            )
            await _remove_inline_keyboard(callback)
            await callback.answer("Спасибо.")
            if callback.message:
                await callback.message.answer(
                    "Опишите, пожалуйста, проблему и приложите скриншоты переписки или "
                    "другие подтверждения. Это поможет нам разобраться в ситуации и принять меры.\n"
                    "👉 Напишите текст, прикрепите фото и нажмите «Отправить».",
                    reply_markup=_issue_send_keyboard(),
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
            await _remove_inline_keyboard(callback)
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
            await _remove_inline_keyboard(callback)
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
            await _remove_inline_keyboard(callback)
            await callback.answer("Спасибо, ответ сохранен.")
    except Exception:
        await callback.answer("Произошла ошибка. Попробуйте позже.")
        return
