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

from ugc_bot.application.messenger.context import (
    CallbackContext,
    MessageContext,
)
from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_complaint,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.nps_service import NpsService
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
)
from ugc_bot.domain.enums import MessengerType

router = Router()
logger = logging.getLogger(__name__)


class FeedbackStates(StatesGroup):
    """FSM states for feedback (no_deal text, issue, NPS comment)."""

    waiting_no_deal_other = State()
    waiting_issue_description = State()
    waiting_nps_comment = State()


_FEEDBACK_TEXT_MAP = {
    "ok": "✅ Всё прошло нормально",
    "no_deal": "❌ Не договорились",
    "postpone": "⏳ Ещё не связался",
    "issue": "⚠️ Проблема / подозрение на мошенничество",
}

# No-deal reason keys (blogger: 4; advertiser: 4, different third)
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


async def _remove_inline_keyboard(
    callback: CallbackQuery | CallbackContext,
) -> None:
    """Remove inline keyboard from message after user selection."""
    if callback.message:
        edit_reply_markup = getattr(callback.message, "edit_reply_markup", None)
        if callable(edit_reply_markup):
            await edit_reply_markup(reply_markup=None)


def _parse_uuid_hex(hex_str: str) -> UUID:
    """Parse 32-char hex string to UUID."""
    return UUID(hex=hex_str)


def _no_deal_reason_keyboard(
    kind: str, interaction_id: UUID
) -> InlineKeyboardMarkup:
    """Build inline keyboard for no_deal reason (blogger or advertiser)."""
    reasons = (
        _NO_DEAL_REASONS_ADVERTISER
        if kind == "adv"
        else _NO_DEAL_REASONS_BLOGGER
    )
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


_NPS_DONE_BUTTON = "Готово"
_NPS_THANK = (
    "Благодарю! 🙌\n"
    "Ваш отзыв сохранён, он помогает нам делать платформу UMC лучше🙏"
)

# 1. Вопрос оценки
_NPS_QUESTION = (
    "Оцените, пожалуйста, работу с платформой UMC по шкале от 1 до 5 ⭐"
)

# 2. Ветка «5 ⭐» — всё супер
_NPS_PROMPT_5_ADV = (
    "Спасибо за оценку 5 ⭐ — очень рады, что вам было удобно работать "
    "с платформой UMC! 🙌\n"
    "Если есть 1–2 идеи, как сделать сервис ещё удобнее (интерфейс, "
    "подбор креаторов, уведомления и т. д.) — напишите в ответ.\n"
    "Мы внимательно читаем каждое предложение для развития платформы."
)
_NPS_PROMPT_5_BLOG = (
    "Спасибо за оценку 5 ⭐ — очень рады, что вам комфортно работать "
    "с заказчиками через платформу UMC! 🙌\n"
    "Если есть 1–2 идеи, как улучшить сервис (личный кабинет, подбор "
    "заказов, условия, поддержка) — напишите в ответ.\n"
    "Мы внимательно читаем каждое предложение для развития платформы."
)

# 3. Ветка «2–4 ⭐» — в целом ок, но есть вопросы
_NPS_PROMPT_34_ADV = (
    "Спасибо за вашу оценку 🙏\n"
    "Нам важно понять, что именно можно улучшить в работе с UMC.\n"
    "Пожалуйста, в одном сообщении напишите:\n"
    "– что не устроило (подбор, скорость, интерфейс, коммуникация)."
)
_NPS_PROMPT_34_BLOG = (
    "Спасибо за вашу оценку 🙏\n"
    "Нам важно понимать, что можно улучшить в работе с заказами через UMC.\n"
    "Пожалуйста, в одном сообщении напишите:\n"
    "– что было сложно или неудобно (условия, общение с заказчиком, интерфейс, "
    "уведомления и т. д.)."
)

# 4. Ветка «1 ⭐» — всё плохо, нужен разбор
_NPS_PROMPT_1_ADV = (
    "Спасибо, что честно поставили 1 ⭐ — нам правда важно это знать 🙏\n"
    "Нам очень жаль, что опыт работы с платформой UMC оказался негативным.\n"
    "Пожалуйста, опишите в одном сообщении, что именно пошло не так:\n"
    "– проблемы с креатором;\n"
    "– сложности с платформой;\n"
    "– ошибки, задержки, недопонимание и т. д.\n"
    "Мы внимательно разберём ситуацию."
)
_NPS_PROMPT_1_BLOG = (
    "Спасибо, что честно поставили 1 ⭐ — нам правда важно это знать 🙏\n"
    "Нам очень жаль, что опыт работы через UMC оказался негативным.\n"
    "Пожалуйста, опишите в одном сообщении, что именно произошло:\n"
    "– проблемы с заказчиком;\n"
    "– сложность условий;\n"
    "– технические проблемы платформы;\n"
    "– любые другие моменты.\n"
    "Мы внимательно разберём ситуацию."
)


def _get_nps_comment_prompt(score: int, kind: str) -> str:
    """Return branch-specific prompt for NPS follow-up (adv/blog)."""
    if score == 5:
        return _NPS_PROMPT_5_ADV if kind == "adv" else _NPS_PROMPT_5_BLOG
    if score in (2, 3, 4):
        return _NPS_PROMPT_34_ADV if kind == "adv" else _NPS_PROMPT_34_BLOG
    return _NPS_PROMPT_1_ADV if kind == "adv" else _NPS_PROMPT_1_BLOG


def _nps_keyboard(user_id: UUID, kind: str) -> Keyboard:
    """Build inline keyboard for NPS 1-5 (star labels)."""
    id_hex = _uuid_hex(user_id)
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=f"{i} ⭐",
                    callback_data=f"nps:{id_hex}:{i}:{kind}",
                )
                for i in range(1, 6)
            ]
        ],
    )


def _nps_comment_keyboard() -> ReplyKeyboardMarkup:
    """Reply keyboard with 'Готово' for optional NPS comment."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=_NPS_DONE_BUTTON)]],
        resize_keyboard=True,
    )


async def _advertiser_has_feedback_for_bloggers_needed(
    interaction: "Interaction",
    interaction_service: InteractionService,
    order_service: OrderService,
) -> bool:
    """Check if advertiser gave feedback for bloggers_needed interactions."""
    order = await order_service.get_order(interaction.order_id)
    if order is None:
        return False
    interactions = await interaction_service.list_interactions_by_order(
        interaction.order_id
    )
    count_with_feedback = sum(
        1 for i in interactions if i.from_advertiser is not None
    )
    return count_with_feedback >= order.bloggers_needed


def _can_access_interaction(
    kind: str, interaction: "Interaction", user_id: UUID
) -> bool:
    """Check if user can access interaction for feedback."""
    if kind == "adv":
        return interaction.advertiser_id == user_id
    return interaction.blogger_id == user_id


async def _record_reason_feedback(
    kind: str,
    reason_key: str,
    interaction_id: UUID,
    feedback_text: str,
    interaction: "Interaction",
    callback: CallbackContext,
    blogger_registration_service: BloggerRegistrationService,
    interaction_service: InteractionService,
    nps_service: NpsService,
    order_service: OrderService,
    messenger_client: MessengerClient,
) -> None:
    """Record feedback for selected reason and send NPS if applicable."""
    if kind == "adv":
        await interaction_service.record_advertiser_feedback(
            interaction_id, feedback_text
        )
        if reason_key == "creator_wanted_to_change":
            svc = blogger_registration_service
            await svc.increment_wanted_to_change_terms_count(
                interaction.blogger_id
            )
    else:
        await interaction_service.record_blogger_feedback(
            interaction_id, feedback_text
        )
    await _remove_inline_keyboard(callback)
    await callback.answer("Спасибо, ответ сохранен.")
    if callback.message:
        await callback.message.answer("Спасибо за обратную связь.")
        await _maybe_send_nps(
            kind,
            interaction,
            callback.message.chat.id,
            messenger_client,
            nps_service,
            interaction_service,
            order_service,
        )


async def _handle_feedback_no_deal(
    callback: CallbackContext,
    kind: str,
    interaction_id: UUID,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    messenger_client: MessengerClient,
    incoming: IncomingCallback,
) -> bool:
    """Show no_deal reason keyboard. Returns True if handled."""
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Заблокированные не могут оставлять отзыв.",
        pause_msg="На паузе не могут оставлять отзыв.",
    )
    if user is None:
        return True
    interaction = await interaction_service.get_interaction(interaction_id)
    if interaction is None:
        await callback.answer("Взаимодействие не найдено.")
        return True
    if kind == "adv" and interaction.advertiser_id != user.user_id:
        await callback.answer("Недостаточно прав.")
        return True
    if kind == "blog" and interaction.blogger_id != user.user_id:
        await callback.answer("Недостаточно прав.")
        return True
    await _remove_inline_keyboard(callback)
    await callback.answer()
    if callback.message:
        question = (
            "Подскажите, по какой причине не удалось договориться?"
            if kind == "blog"
            else "По какой причине не удалось договориться?"
        )
        await callback.message.answer(
            question,
            reply_markup=_no_deal_reason_keyboard(kind, interaction_id),
        )
    return True


async def _handle_feedback_issue(
    callback: CallbackContext,
    state: FSMContext,
    kind: str,
    interaction_id: UUID,
) -> None:
    """Transition to issue description state."""
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
            "Опишите проблему и приложите скриншоты переписки или "
            "другие подтверждения. Это поможет разобраться.\n"
            "👉 Напишите текст, прикрепите фото и нажмите «Отправить».",
            reply_markup=_issue_send_keyboard(),
        )


async def _handle_feedback_reply(
    callback: CallbackContext,
    kind: str,
    status_raw: str,
    updated_interaction: "Interaction",
    interaction_service: InteractionService,
    nps_service: NpsService,
    order_service: OrderService,
    messenger_client: MessengerClient,
) -> None:
    """Send reply message for ok/postpone/other status."""
    await _remove_inline_keyboard(callback)
    if status_raw == "postpone":
        max_reached = (
            updated_interaction.postpone_count
            >= interaction_service.max_postpone_count
        )
        if max_reached:
            await callback.answer(
                "Достигнут максимум переносов. "
                "Статус зафиксирован как 'Не договорились'."
            )
            if callback.message:
                await callback.message.answer("Спасибо за обратную связь.")
        else:
            cnt = updated_interaction.postpone_count
            max_cnt = interaction_service.max_postpone_count
            await callback.answer(
                f"Проверка перенесена на 72 ч. Переносов: {cnt}/{max_cnt}"
            )
            if callback.message:
                msg = (
                    "Хорошо, вернёмся к этому позже 👍 "
                    "Если заказчик напишет — просто ответьте ему."
                    if kind == "blog"
                    else (
                        "Поняли, вернёмся к этому позже 👍\n"
                        "ℹ️ Креатор не видит контакты. "
                        "Связь начинается с вашей стороны."
                    )
                )
                await callback.message.answer(msg)
        if callback.message:
            await _maybe_send_nps(
                kind,
                updated_interaction,
                callback.message.chat.id,
                messenger_client,
                nps_service,
                interaction_service,
                order_service,
            )
        return

    if status_raw == "ok":
        await callback.answer("Спасибо, ответ сохранен.")
        if callback.message:
            msg = (
                "Спасибо за обратную связь 👍 "
                "Если понадобится помощь — мы на связи."
                if kind == "blog"
                else "Спасибо за обратную связь 👍 "
                "Желаем удачной работы с креатором."
            )
            await callback.message.answer(msg)
    else:
        await callback.answer("Спасибо, ответ сохранен.")
        if callback.message:
            await callback.message.answer("Спасибо за обратную связь.")

    if callback.message:
        await _maybe_send_nps(
            kind,
            updated_interaction,
            callback.message.chat.id,
            messenger_client,
            nps_service,
            interaction_service,
            order_service,
        )


async def _maybe_send_nps(
    kind: str,
    interaction: "Interaction",
    chat_id: str | int,
    messenger_client: MessengerClient,
    nps_service: NpsService,
    interaction_service: InteractionService,
    order_service: OrderService,
) -> None:
    """Send NPS: blogger after first feedback, adv after bloggers_needed."""
    chat_id = str(chat_id)
    if kind == "blog":
        if await nps_service.exists_for_user(interaction.blogger_id):
            return
        user_id = interaction.blogger_id
    else:
        if not await _advertiser_has_feedback_for_bloggers_needed(
            interaction, interaction_service, order_service
        ):
            return
        user_id = interaction.advertiser_id
    await messenger_client.send_text(
        chat_id=chat_id,
        text=_NPS_QUESTION,
        keyboard=_nps_keyboard(user_id, kind),
    )


def _get_reason_labels() -> dict[str, str]:
    """Build reason_key -> label map for no_deal reasons."""
    labels = {k: label for k, label, _ in _NO_DEAL_REASONS_BLOGGER}
    labels.update({k: label for k, label, _ in _NO_DEAL_REASONS_ADVERTISER})
    return labels


@router.callback_query(lambda c: c.data and c.data.startswith("fb_r:"))
async def handle_feedback_reason(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    blogger_registration_service: BloggerRegistrationService,
    nps_service: NpsService,
    order_service: OrderService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle no_deal reason: record feedback or ask for text (Другое)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    callback_ctx = CallbackContext(incoming, messenger_client)
    if not callback_ctx.data:
        return
    parts = callback_ctx.data.split(":")
    if len(parts) != 4:
        await callback_ctx.answer("Неверный формат.")
        return
    _, kind, interaction_id_raw, reason_code = parts
    try:
        interaction_id = _parse_uuid_hex(interaction_id_raw)
    except (ValueError, TypeError):
        await callback_ctx.answer("Неверный идентификатор.")
        return
    reason_key = _REASON_CODE_TO_KEY.get(reason_code)
    if reason_key is None:
        await callback_ctx.answer("Неверный формат.")
        return

    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Заблокированные пользователи не могут оставлять отзыв.",
        pause_msg="Пользователи на паузе не могут оставлять отзыв.",
    )
    if user is None:
        return

    interaction = await interaction_service.get_interaction(interaction_id)
    if interaction is None:
        await callback_ctx.answer("Взаимодействие не найдено.")
        return
    if not _can_access_interaction(kind, interaction, user.user_id):
        await callback_ctx.answer("Недостаточно прав.")
        return

    if reason_key == "other":
        await state.set_state(FeedbackStates.waiting_no_deal_other)
        await state.update_data(
            feedback_interaction_id=str(interaction_id),
            feedback_kind=kind,
        )
        await _remove_inline_keyboard(callback_ctx)
        await callback_ctx.answer()
        if callback_ctx.message:
            await callback_ctx.message.answer("Напишите, пожалуйста, причину:")
        return

    reason_labels = _get_reason_labels()
    reason_label = reason_labels.get(reason_key, reason_key)
    feedback_text = "❌ Не договорились: " + reason_label

    await _record_reason_feedback(
        kind,
        reason_key,
        interaction_id,
        feedback_text,
        interaction,
        callback_ctx,
        blogger_registration_service,
        interaction_service,
        nps_service,
        order_service,
        messenger_client,
    )


async def _record_no_deal_other_feedback(
    kind: str,
    interaction_id: UUID,
    text: str,
    interaction: "Interaction",
    interaction_service: InteractionService,
) -> None:
    """Record no_deal 'other' feedback and send thank you."""
    feedback_text = "❌ Не договорились: Другое: " + text
    if kind == "adv":
        await interaction_service.record_advertiser_feedback(
            interaction_id, feedback_text
        )
    else:
        await interaction_service.record_blogger_feedback(
            interaction_id, feedback_text
        )


@router.message(FeedbackStates.waiting_no_deal_other)
async def handle_no_deal_other_text(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    nps_service: NpsService,
    order_service: OrderService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle no_deal 'Другое': record feedback and clear state."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)

    if message_ctx.from_user is None:
        return
    text = (message_ctx.text or "").strip()
    if not text:
        await message_ctx.answer("Введите причину текстом.")
        return

    user = await user_role_service.get_user(
        external_id=str(message_ctx.from_user.id),
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
        await message_ctx.answer(
            "Сессия истекла. Ответьте на вопрос обратной связи снова."
        )
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
    if not _can_access_interaction(kind, interaction, user.user_id):
        await message.answer("Недостаточно прав.")
        return

    await _record_no_deal_other_feedback(
        kind, interaction_id, text, interaction, interaction_service
    )
    await message_ctx.answer("Спасибо за обратную связь.")
    await _maybe_send_nps(
        kind,
        interaction,
        message_ctx.chat.id,
        messenger_client,
        nps_service,
        interaction_service,
        order_service,
    )


async def _handle_issue_send_button(
    message: MessageContext,
    state: FSMContext,
    interaction_id_raw: str,
    kind: str,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    complaint_service: ComplaintService,
    nps_service: NpsService,
    order_service: OrderService,
    messenger_client: MessengerClient,
) -> bool:
    """Handle 'Отправить' button: validate and create complaint."""
    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await state.clear()
        await message.answer("Ошибка. Попробуйте снова.")
        return True
    user = await user_role_service.get_user(
        external_id=str(message.from_user.id) if message.from_user else "",
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await state.clear()
        return True
    interaction = await interaction_service.get_interaction(interaction_id)
    if interaction is None:
        await state.clear()
        await message.answer("Взаимодействие не найдено.")
        return True
    if not _can_access_interaction(kind, interaction, user.user_id):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return True
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
        nps_service,
        order_service,
        messenger_client,
    )
    return True


async def _handle_issue_append_content(
    message: MessageContext,
    state: FSMContext,
    text: str,
    new_file_ids: list[str],
    interaction_id_raw: str,
    kind: str,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    issue_lock_manager: "IssueDescriptionLockManager",
) -> None:
    """Append text/photos to issue and confirm."""
    user = await user_role_service.get_user(
        external_id=str(message.from_user.id) if message.from_user else "",
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
    if not _can_access_interaction(kind, interaction, user.user_id):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return
    user_key = str(message.from_user.id) if message.from_user else ""
    async with issue_lock_manager.lock(user_key):
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
    await message.answer("\u200b", reply_markup=_issue_send_keyboard())


@router.message(FeedbackStates.waiting_issue_description)
async def handle_issue_description(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    complaint_service: ComplaintService,
    issue_lock_manager: "IssueDescriptionLockManager",
    nps_service: NpsService,
    order_service: OrderService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Collect issue description/photos; complaint on 'Отправить' button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)

    if message_ctx.from_user is None:
        return
    text = (message_ctx.text or "").strip()
    photos = getattr(message_ctx, "photo", None)
    new_file_ids = [photos[-1].file_id] if photos else []

    data = await state.get_data()
    interaction_id_raw = data.get("feedback_interaction_id")
    kind = data.get("feedback_kind")
    if not interaction_id_raw or kind not in ("adv", "blog"):
        await state.clear()
        await message_ctx.answer(
            "Сессия истекла. Ответьте на вопрос обратной связи снова."
        )
        return

    if text == _ISSUE_SEND_BUTTON_TEXT:
        await _handle_issue_send_button(
            message_ctx,
            state,
            interaction_id_raw,
            kind,
            user_role_service,
            interaction_service,
            complaint_service,
            nps_service,
            order_service,
            messenger_client,
        )
        return

    if not text and not new_file_ids:
        await message_ctx.answer(
            "Добавьте описание или фото, затем нажмите «Отправить».",
            reply_markup=_issue_send_keyboard(),
        )
        return

    await _handle_issue_append_content(
        message_ctx,
        state,
        text,
        new_file_ids,
        interaction_id_raw,
        kind,
        user_role_service,
        interaction_service,
        issue_lock_manager,
    )


async def _create_complaint_from_issue(
    message: MessageContext,
    state: FSMContext,
    interaction_id: UUID,
    kind: str,
    user: "User",
    interaction: "Interaction",
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    complaint_service: ComplaintService,
    nps_service: NpsService,
    order_service: OrderService,
    messenger_client: MessengerClient,
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
    reported_id = (
        interaction.blogger_id if kind == "adv" else interaction.advertiser_id
    )

    try:
        complaint = await complaint_service.create_complaint(
            reporter_id=reporter_id,
            reported_id=reported_id,
            order_id=interaction.order_id,
            reason=reason,
            file_ids=file_ids if file_ids else None,
        )
        await notify_admins_about_complaint(
            complaint, messenger_client, user_role_service
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
            "Произошла ошибка при создании заявки. Попробуйте снова "
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
        await interaction_service.record_blogger_feedback(
            interaction_id, feedback_text
        )

    await state.clear()
    await message.answer(
        "Мы приняли вашу заявку. Поддержка разберётся в ситуации. "
        "При необходимости нажмите «Поддержка» в меню.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await _maybe_send_nps(
        kind,
        interaction,
        message.chat.id,
        messenger_client,
        nps_service,
        interaction_service,
        order_service,
    )
    return True


@router.callback_query(lambda c: c.data and c.data.startswith("nps:"))
async def handle_nps(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    nps_service: NpsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle NPS score (1-5); show branch prompt, transition to comment."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    callback_ctx = CallbackContext(incoming, messenger_client)
    if not callback_ctx.data:
        return
    parts = callback_ctx.data.split(":")
    if len(parts) not in (3, 4):
        await callback_ctx.answer("Неверный формат.")
        return
    _, user_id_raw, score_raw = parts[:3]
    kind = parts[3] if len(parts) == 4 else "blog"
    if kind not in ("adv", "blog"):
        kind = "blog"
    try:
        user_id = _parse_uuid_hex(user_id_raw)
        score = int(score_raw)
    except (ValueError, TypeError):
        await callback_ctx.answer("Неверный формат.")
        return
    if score < 1 or score > 5:
        await callback_ctx.answer("Оценка должна быть от 1 до 5.")
        return

    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Заблокированные пользователи не могут оценивать.",
        pause_msg="Пользователи на паузе не могут оценивать.",
    )
    if user is None:
        return
    if user.user_id != user_id:
        await callback_ctx.answer("Недостаточно прав.")
        return

    await state.set_state(FeedbackStates.waiting_nps_comment)
    await state.update_data(
        nps_user_id=str(user_id),
        nps_score=score,
        nps_kind=kind,
    )
    await _remove_inline_keyboard(callback_ctx)
    await callback_ctx.answer("Спасибо за оценку!")
    prompt = _get_nps_comment_prompt(score, kind)
    if callback_ctx.message:
        await callback_ctx.message.answer(
            prompt,
            reply_markup=_nps_comment_keyboard(),
        )


@router.message(FeedbackStates.waiting_nps_comment)
async def handle_nps_comment(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    nps_service: NpsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle optional NPS comment or 'Готово'; save and thank user."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)
    if message_ctx.from_user is None:
        return
    text = (message_ctx.text or "").strip()
    if text == _NPS_DONE_BUTTON:
        text = ""

    user = await user_role_service.get_user(
        external_id=str(message_ctx.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await state.clear()
        return

    data = await state.get_data()
    await state.clear()
    user_id_raw = data.get("nps_user_id")
    score = data.get("nps_score")
    if not user_id_raw or score is None:
        await message_ctx.answer(
            "Сессия истекла. Ответьте на вопрос оценки снова."
        )
        return

    try:
        user_id = UUID(user_id_raw)
    except ValueError:
        await message_ctx.answer("Ошибка. Попробуйте снова.")
        return

    if user.user_id != user_id:
        await message_ctx.answer("Недостаточно прав.")
        return

    await nps_service.save(user_id, score, comment=text or None)
    await message_ctx.answer(
        _NPS_THANK,
        reply_markup=ReplyKeyboardRemove(),
    )


async def _handle_feedback_status_flow(
    callback: CallbackContext,
    state: FSMContext,
    kind: str,
    interaction_id: UUID,
    status_raw: str,
    feedback_text: str,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    nps_service: NpsService,
    order_service: OrderService,
    messenger_client: MessengerClient,
    incoming: IncomingCallback,
) -> None:
    """Get user, validate access, then handle ok/postpone/issue."""
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
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
        if not _can_access_interaction(kind, interaction, user.user_id):
            await callback.answer("Недостаточно прав.")
            return
        await _handle_feedback_ok_postpone_issue(
            callback,
            state,
            kind,
            interaction_id,
            status_raw,
            feedback_text,
            user,
            interaction_service,
            nps_service,
            order_service,
            messenger_client,
        )
    except Exception:
        await callback.answer("Произошла ошибка. Попробуйте позже.")
        return


async def _handle_feedback_ok_postpone_issue(
    callback: CallbackContext,
    state: FSMContext,
    kind: str,
    interaction_id: UUID,
    status_raw: str,
    feedback_text: str,
    user: "User",
    interaction_service: InteractionService,
    nps_service: NpsService,
    order_service: OrderService,
    messenger_client: MessengerClient,
) -> None:
    """Handle ok/postpone/issue: record or transition to issue flow."""
    if status_raw == "issue":
        await _handle_feedback_issue(callback, state, kind, interaction_id)
        return
    if kind == "adv":
        updated = await interaction_service.record_advertiser_feedback(
            interaction_id, feedback_text
        )
    else:
        updated = await interaction_service.record_blogger_feedback(
            interaction_id, feedback_text
        )
    await _handle_feedback_reply(
        callback,
        kind,
        status_raw,
        updated,
        interaction_service,
        nps_service,
        order_service,
        messenger_client,
    )


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("feedback:")
)
async def handle_feedback(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    nps_service: NpsService,
    order_service: OrderService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle feedback callbacks from advertiser or blogger."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    callback_ctx = CallbackContext(incoming, messenger_client)
    if not callback_ctx.data:
        return

    parts = callback_ctx.data.split(":")
    if len(parts) != 4:
        await callback_ctx.answer("Неверный формат ответа.")
        return

    _, kind, interaction_id_raw, status_raw = parts

    if status_raw == "no_deal":
        try:
            interaction_id = UUID(interaction_id_raw)
        except ValueError:
            await callback_ctx.answer("Неверный идентификатор.")
            return
        await _handle_feedback_no_deal(
            callback_ctx,
            kind,
            interaction_id,
            user_role_service,
            interaction_service,
            messenger_client,
            incoming,
        )
        return

    feedback_text = _FEEDBACK_TEXT_MAP.get(status_raw)
    if feedback_text is None:
        await callback_ctx.answer("Неверный статус.")
        return

    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await callback_ctx.answer("Неверный идентификатор.")
        return

    await _handle_feedback_status_flow(
        callback_ctx,
        state,
        kind,
        interaction_id,
        status_raw,
        feedback_text,
        user_role_service,
        interaction_service,
        nps_service,
        order_service,
        messenger_client,
        incoming,
    )
