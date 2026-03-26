"""Max handlers for feedback after contacts sharing."""

import contextlib
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.state import StateStore
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
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.telegram.handlers.feedback import (
    _REASON_CODE_TO_KEY,
    FEEDBACK_TEXTS_KEYS,
    _advertiser_has_feedback_for_bloggers_needed,
    _can_access_interaction,
    _feedback_text_map,
    _get_nps_comment_prompt,
    _get_reason_labels,
    _no_deal_reasons_advertiser,
    _no_deal_reasons_blogger,
    _parse_uuid_hex,
    _record_no_deal_other_feedback,
    _uuid_hex,
)
from ugc_bot.domain.enums import MessengerType, UserStatus

if TYPE_CHECKING:
    from ugc_bot.application.messenger.ports import MessengerClient
    from ugc_bot.domain.entities import Interaction, User

router = MaxRouter()
logger = logging.getLogger(__name__)

STATE_FEEDBACK_TEXT = "feedback_text"
STATE_FEEDBACK_ISSUE_TEXT = "feedback_issue_text"
STATE_FEEDBACK_NPS_COMMENT = "feedback_nps_comment"


def _nps_keyboard_max(user_id: UUID, kind: str) -> Keyboard:
    """Build inline NPS 1-5 keyboard for Max."""
    id_hex = _uuid_hex(user_id)
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=f"{i} звезд",
                    callback_data=f"nps:{id_hex}:{i}:{kind}",
                )
                for i in range(1, 6)
            ]
        ],
    )


def _no_deal_reason_keyboard_max(
    kind: str, interaction_id: UUID, texts: dict[str, str]
) -> Keyboard:
    """Build inline keyboard for no_deal reasons (Max)."""
    reasons = (
        _no_deal_reasons_advertiser(texts)
        if kind == "adv"
        else _no_deal_reasons_blogger(texts)
    )
    id_hex = _uuid_hex(interaction_id)
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=label,
                    callback_data=f"fb_r:{kind}:{id_hex}:{code}",
                )
            ]
            for _key, label, code in reasons
        ],
    )


async def _maybe_send_nps_max(
    kind: str,
    interaction: "Interaction",
    chat_id: str,
    messenger_client: "MessengerClient",
    nps_service: NpsService,
    interaction_service: InteractionService,
    order_service: OrderService,
    texts: dict[str, str],
) -> None:
    """Send NPS after feedback (Max version)."""
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
        text=texts.get("msg_fb_nps_question", ""),
        keyboard=_nps_keyboard_max(user_id, kind),
    )


async def _handle_feedback_no_deal(
    incoming: IncomingCallback,
    kind: str,
    interaction_id: UUID,
    messenger_client: "MessengerClient",
    texts: dict[str, str],
) -> None:
    """Handle no_deal status in feedback callback."""
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )
    question = (
        texts.get("msg_fb_no_deal_question_blog", "")
        if kind == "blog"
        else texts.get("msg_fb_no_deal_question_adv", "")
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=question,
        keyboard=_no_deal_reason_keyboard_max(kind, interaction_id, texts),
    )


async def _handle_feedback_issue(
    incoming: IncomingCallback,
    kind: str,
    interaction_id: UUID,
    messenger_client: "MessengerClient",
    state_store: StateStore,
    texts: dict[str, str],
) -> None:
    """Handle issue status in feedback callback."""
    await state_store.set_state(STATE_FEEDBACK_ISSUE_TEXT)
    await state_store.update_data(
        feedback_interaction_id=str(interaction_id),
        feedback_kind=kind,
        issue_description_parts=[],
    )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text=texts.get("msg_fb_thanks_short", "Спасибо."),
    )
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=texts.get("msg_fb_issue_prompt", ""),
    )


async def _handle_feedback_postpone(
    incoming: IncomingCallback,
    kind: str,
    updated: "Interaction",
    messenger_client: "MessengerClient",
    interaction_service: InteractionService,
    texts: dict[str, str],
) -> None:
    """Handle postpone status response after recording feedback."""
    max_cnt = interaction_service.max_postpone_count
    max_reached = updated.postpone_count >= max_cnt
    if max_reached:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_postpone_max", ""),
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_thanks_feedback", ""),
        )
    else:
        cnt = updated.postpone_count
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_postpone_72", "").format(
                cnt=cnt, max_cnt=max_cnt
            ),
        )
        msg = (
            texts.get("msg_fb_postpone_ok_blog", "")
            if kind == "blog"
            else texts.get("msg_fb_postpone_ok_adv", "")
        )
        await messenger_client.send_text(chat_id=incoming.chat_id, text=msg)


async def _send_feedback_response(
    incoming: IncomingCallback,
    kind: str,
    status_raw: str,
    updated: "Interaction",
    messenger_client: "MessengerClient",
    interaction_service: InteractionService,
    nps_service: NpsService,
    order_service: OrderService,
    texts: dict[str, str],
) -> None:
    """Remove reply markup and dispatch the appropriate status response."""
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )

    if status_raw == "postpone":
        await _handle_feedback_postpone(
            incoming,
            kind,
            updated,
            messenger_client,
            interaction_service,
            texts,
        )
    elif status_raw == "ok":
        await _handle_feedback_ok(incoming, kind, messenger_client, texts)
    else:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_thanks_saved", ""),
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_thanks_feedback", ""),
        )

    await _maybe_send_nps_max(
        kind,
        updated,
        incoming.chat_id,
        messenger_client,
        nps_service,
        interaction_service,
        order_service,
        texts,
    )


async def _record_feedback(
    kind: str,
    interaction_id: UUID,
    feedback_text_val: str,
    interaction_service: InteractionService,
) -> "Interaction":
    """Record advertiser or blogger feedback and return updated interaction."""
    if kind == "adv":
        return await interaction_service.record_advertiser_feedback(
            interaction_id, feedback_text_val
        )
    return await interaction_service.record_blogger_feedback(
        interaction_id, feedback_text_val
    )


async def _handle_feedback_ok(
    incoming: IncomingCallback,
    kind: str,
    messenger_client: "MessengerClient",
    texts: dict[str, str],
) -> None:
    """Handle ok status response after recording feedback."""
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text=texts.get("msg_fb_thanks_saved", ""),
    )
    msg = (
        texts.get("msg_fb_ok_blog", "")
        if kind == "blog"
        else texts.get("msg_fb_ok_adv", "")
    )
    await messenger_client.send_text(chat_id=incoming.chat_id, text=msg)


def _user_access_error(
    user: "User | None", allow_msgs: dict[str, str]
) -> str | None:
    """Return an error message if user cannot access feedback, else None."""
    if user is None:
        return allow_msgs.get("msg_user_not_found", "")
    if user.status == UserStatus.BLOCKED:
        return allow_msgs.get("msg_feedback_blocked", "")
    if user.status == UserStatus.PAUSE:
        return allow_msgs.get("msg_feedback_pause", "")
    return None


async def _resolve_interaction(
    interaction_id_raw: str,
    kind: str,
    user: "User",
    incoming: IncomingCallback,
    messenger_client: "MessengerClient",
    interaction_service: InteractionService,
    texts: dict[str, str],
) -> tuple[UUID | None, "Interaction | None"]:
    """Parse, fetch and validate interaction; return (id, interaction)."""
    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_invalid_id", "Неверный идентификатор."),
        )
        return None, None

    interaction = await interaction_service.get_interaction(
        interaction_id,
    )
    if interaction is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get(
                "msg_fb_interaction_not_found",
                "Взаимодействие не найдено.",
            ),
        )
        return None, None

    if not _can_access_interaction(kind, interaction, user.user_id):
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get(
                "msg_fb_insufficient_rights",
                "Недостаточно прав.",
            ),
        )
        return None, None

    return interaction_id, interaction


@router.callback(lambda cb: bool(cb.data and cb.data.startswith("feedback:")))
async def handle_feedback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Handle feedback callbacks from advertiser or blogger."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    interaction_service: InteractionService = deps["interaction_service"]
    nps_service: NpsService = deps["nps_service"]
    order_service: OrderService = deps["order_service"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    if not incoming.data:
        return

    allow_keys = [
        "msg_user_not_found",
        "msg_feedback_blocked",
        "msg_feedback_pause",
    ]
    all_msgs = await bot_texts_service.get_many(
        allow_keys + FEEDBACK_TEXTS_KEYS, locale
    )
    allow_msgs = {k: all_msgs.get(k, "") for k in allow_keys}
    texts = {k: all_msgs.get(k, "") for k in FEEDBACK_TEXTS_KEYS}

    parts = incoming.data.split(":")
    if len(parts) != 4:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get(
                "msg_fb_invalid_response", "Неверный формат ответа."
            ),
        )
        return

    _, kind, interaction_id_raw, status_raw = parts

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    err = _user_access_error(user, allow_msgs)
    if err is not None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id, text=err
        )
        return

    assert user is not None
    interaction_id, interaction = await _resolve_interaction(
        interaction_id_raw,
        kind,
        user,
        incoming,
        messenger_client,
        interaction_service,
        texts,
    )
    if interaction is None:
        return
    assert interaction_id is not None

    if status_raw == "no_deal":
        await _handle_feedback_no_deal(
            incoming, kind, interaction_id, messenger_client, texts
        )
        return

    if status_raw == "issue":
        await _handle_feedback_issue(
            incoming, kind, interaction_id, messenger_client, state_store, texts
        )
        return

    feedback_text_val = _feedback_text_map(texts).get(status_raw)
    if feedback_text_val is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_invalid_status", "Неверный статус."),
        )
        return

    try:
        updated = await _record_feedback(
            kind, interaction_id, feedback_text_val, interaction_service
        )
    except Exception:
        logger.exception("Error recording feedback")
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get(
                "msg_fb_error_try_later",
                "Произошла ошибка. Попробуйте позже.",
            ),
        )
        return

    await _send_feedback_response(
        incoming,
        kind,
        status_raw,
        updated,
        messenger_client,
        interaction_service,
        nps_service,
        order_service,
        texts,
    )


async def _handle_reason_other(
    incoming: IncomingCallback,
    kind: str,
    interaction_id: UUID,
    messenger_client: "MessengerClient",
    state_store: StateStore,
    texts: dict[str, str],
) -> None:
    """Handle 'other' reason selection — prompt for free text."""
    await state_store.set_state(STATE_FEEDBACK_TEXT)
    await state_store.update_data(
        feedback_interaction_id=str(interaction_id),
        feedback_kind=kind,
    )
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=texts.get(
            "msg_fb_no_deal_other_prompt", "Напишите, пожалуйста, причину:"
        ),
    )


async def _record_reason_and_respond(
    incoming: IncomingCallback,
    kind: str,
    interaction_id: UUID,
    feedback_text_val: str,
    reason_key: str,
    interaction: "Interaction",
    messenger_client: "MessengerClient",
    interaction_service: InteractionService,
    blogger_registration_service: BloggerRegistrationService,
    nps_service: NpsService,
    order_service: OrderService,
    texts: dict[str, str],
) -> None:
    """Record no_deal reason feedback, clear keyboard, and thank the user."""
    if kind == "adv":
        await interaction_service.record_advertiser_feedback(
            interaction_id, feedback_text_val
        )
        if reason_key == "creator_wanted_to_change":
            svc = blogger_registration_service
            await svc.increment_wanted_to_change_terms_count(
                interaction.blogger_id
            )
    else:
        await interaction_service.record_blogger_feedback(
            interaction_id, feedback_text_val
        )

    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text=texts.get("msg_fb_thanks_saved", "Спасибо, ответ сохранен."),
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=texts.get("msg_fb_thanks_feedback", "Спасибо за обратную связь."),
    )
    await _maybe_send_nps_max(
        kind,
        interaction,
        incoming.chat_id,
        messenger_client,
        nps_service,
        interaction_service,
        order_service,
        texts,
    )


@router.callback(lambda cb: bool(cb.data and cb.data.startswith("fb_r:")))
async def handle_feedback_reason(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Handle no_deal reason selection callback."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    interaction_service: InteractionService = deps["interaction_service"]
    blogger_registration_service: BloggerRegistrationService = deps[
        "blogger_registration_service"
    ]
    nps_service: NpsService = deps["nps_service"]
    order_service: OrderService = deps["order_service"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    if not incoming.data:
        return

    all_msgs = await bot_texts_service.get_many(
        ["msg_user_not_found", "msg_feedback_blocked", "msg_feedback_pause"]
        + FEEDBACK_TEXTS_KEYS,
        locale,
    )
    texts = {k: all_msgs.get(k, "") for k in FEEDBACK_TEXTS_KEYS}

    parts = incoming.data.split(":")
    if len(parts) != 4:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_invalid_format", "Неверный формат."),
        )
        return
    _, kind, interaction_id_raw, reason_code = parts
    try:
        interaction_id = _parse_uuid_hex(interaction_id_raw)
    except (ValueError, TypeError):
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_invalid_id", "Неверный идентификатор."),
        )
        return
    reason_key = _REASON_CODE_TO_KEY.get(reason_code)
    if reason_key is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_invalid_format", "Неверный формат."),
        )
        return

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=all_msgs.get("msg_user_not_found", ""),
        )
        return

    interaction = await interaction_service.get_interaction(interaction_id)
    if interaction is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get(
                "msg_fb_interaction_not_found", "Взаимодействие не найдено."
            ),
        )
        return
    if not _can_access_interaction(kind, interaction, user.user_id):
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_insufficient_rights", "Недостаточно прав."),
        )
        return

    if reason_key == "other":
        await _handle_reason_other(
            incoming, kind, interaction_id, messenger_client, state_store, texts
        )
        return

    reason_labels = _get_reason_labels(texts)
    reason_label = reason_labels.get(reason_key, reason_key)
    no_deal_prefix = texts.get("msg_fb_feedback_no_deal", "Не договорились")
    feedback_text_val = f"{no_deal_prefix}: {reason_label}"

    await _record_reason_and_respond(
        incoming,
        kind,
        interaction_id,
        feedback_text_val,
        reason_key,
        interaction,
        messenger_client,
        interaction_service,
        blogger_registration_service,
        nps_service,
        order_service,
        texts,
    )


@router.message_in_state(STATE_FEEDBACK_TEXT)
async def handle_no_deal_other_text(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle no_deal 'other' text input — record feedback and clear state."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    interaction_service: InteractionService = deps["interaction_service"]
    nps_service: NpsService = deps["nps_service"]
    order_service: OrderService = deps["order_service"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    texts = await bot_texts_service.get_many(FEEDBACK_TEXTS_KEYS, locale)
    text = (incoming.text or "").strip()
    if not text:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get(
                "msg_fb_enter_reason_text", "Введите причину текстом."
            ),
        )
        return

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await state_store.clear()
        return

    data = await state_store.get_data()
    await state_store.clear()
    interaction_id_raw = data.get("feedback_interaction_id")
    kind = data.get("feedback_kind")
    if not interaction_id_raw or kind not in ("adv", "blog"):
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_session_expired", ""),
        )
        return

    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get(
                "msg_fb_error_try_again", "Ошибка. Попробуйте снова."
            ),
        )
        return

    interaction = await interaction_service.get_interaction(interaction_id)
    if interaction is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get(
                "msg_fb_interaction_not_found", "Взаимодействие не найдено."
            ),
        )
        return
    if not _can_access_interaction(kind, interaction, user.user_id):
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_insufficient_rights", "Недостаточно прав."),
        )
        return

    await _record_no_deal_other_feedback(
        kind, interaction_id, text, interaction, interaction_service
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=texts.get("msg_fb_thanks_feedback", "Спасибо за обратную связь."),
    )
    await _maybe_send_nps_max(
        kind,
        interaction,
        incoming.chat_id,
        messenger_client,
        nps_service,
        interaction_service,
        order_service,
        texts,
    )


async def _handle_issue_submit(
    incoming: IncomingMessage,
    kind: str,
    interaction_id_raw: str,
    data: dict,
    messenger_client: "MessengerClient",
    user_role_service: UserRoleService,
    interaction_service: InteractionService,
    complaint_service: ComplaintService,
    nps_service: NpsService,
    order_service: OrderService,
    state_store: StateStore,
    texts: dict[str, str],
) -> None:
    """Submit the collected issue description as a complaint."""
    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await state_store.clear()
        return

    try:
        interaction_id = UUID(interaction_id_raw)
    except ValueError:
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get(
                "msg_fb_error_try_again", "Ошибка. Попробуйте снова."
            ),
        )
        return

    interaction = await interaction_service.get_interaction(interaction_id)
    if interaction is None:
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get(
                "msg_fb_interaction_not_found", "Взаимодействие не найдено."
            ),
        )
        return
    if not _can_access_interaction(kind, interaction, user.user_id):
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_insufficient_rights", "Недостаточно прав."),
        )
        return

    parts_list = data.get("issue_description_parts") or []
    if not parts_list:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_add_description_before_send", ""),
        )
        return

    no_desc = texts.get("msg_fb_no_description", "Без описания")
    reason = "\n\n".join(parts_list) if parts_list else no_desc
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
        )
        await notify_admins_about_complaint(
            complaint, messenger_client, user_role_service
        )
    except Exception:
        logger.exception("Failed to create complaint from feedback issue")
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_complaint_error", ""),
        )
        return

    feedback_text_val = texts.get("msg_fb_feedback_issue", "")
    if kind == "adv":
        await interaction_service.record_advertiser_feedback(
            interaction_id, feedback_text_val
        )
    else:
        await interaction_service.record_blogger_feedback(
            interaction_id, feedback_text_val
        )

    await state_store.clear()
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=texts.get("msg_fb_complaint_accepted", ""),
    )
    await _maybe_send_nps_max(
        kind,
        interaction,
        incoming.chat_id,
        messenger_client,
        nps_service,
        interaction_service,
        order_service,
        texts,
    )


@router.message_in_state(STATE_FEEDBACK_ISSUE_TEXT)
async def handle_issue_description(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Collect issue description text; send complaint on /send command."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    interaction_service: InteractionService = deps["interaction_service"]
    complaint_service: ComplaintService = deps["complaint_service"]
    nps_service: NpsService = deps["nps_service"]
    order_service: OrderService = deps["order_service"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    texts = await bot_texts_service.get_many(FEEDBACK_TEXTS_KEYS, locale)

    data = await state_store.get_data()
    interaction_id_raw = data.get("feedback_interaction_id")
    kind = data.get("feedback_kind")
    if not interaction_id_raw or kind not in ("adv", "blog"):
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_session_expired", ""),
        )
        return

    text = (incoming.text or "").strip()
    send_btn_text = texts.get("msg_fb_issue_send_btn", "Отправить")

    # Treat "/send" or the send button text as submit signal
    if text in ("/send", send_btn_text):
        await _handle_issue_submit(
            incoming,
            kind,
            interaction_id_raw,
            data,
            messenger_client,
            user_role_service,
            interaction_service,
            complaint_service,
            nps_service,
            order_service,
            state_store,
            texts,
        )
        return

    if not text:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_add_description_photo", ""),
        )
        return

    parts_list = list(data.get("issue_description_parts") or [])
    parts_list.append(text)
    await state_store.update_data(issue_description_parts=parts_list)
    # Confirm receipt
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=texts.get("msg_fb_add_description_before_send", ""),
    )


@router.callback(lambda cb: bool(cb.data and cb.data.startswith("nps:")))
async def handle_nps(incoming: IncomingCallback, deps: dict[str, Any]) -> None:
    """Handle NPS score (1-5); show branch prompt, transition to comment."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    if not incoming.data:
        return

    all_msgs = await bot_texts_service.get_many(
        [
            "msg_user_not_found",
            "msg_feedback_rate_blocked",
            "msg_feedback_rate_pause",
        ]
        + FEEDBACK_TEXTS_KEYS,
        locale,
    )
    texts = {k: all_msgs.get(k, "") for k in FEEDBACK_TEXTS_KEYS}

    parts = incoming.data.split(":")
    if len(parts) not in (3, 4):
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_invalid_format", "Неверный формат."),
        )
        return
    _, user_id_raw, score_raw = parts[:3]
    kind = parts[3] if len(parts) == 4 else "blog"
    if kind not in ("adv", "blog"):
        kind = "blog"
    try:
        user_id = _parse_uuid_hex(user_id_raw)
        score = int(score_raw)
    except (ValueError, TypeError):
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_invalid_format", "Неверный формат."),
        )
        return
    if score < 1 or score > 5:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get(
                "msg_fb_score_1_to_5", "Оценка должна быть от 1 до 5."
            ),
        )
        return

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=all_msgs.get("msg_user_not_found", ""),
        )
        return
    if user.user_id != user_id:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=texts.get("msg_fb_insufficient_rights", "Недостаточно прав."),
        )
        return

    await state_store.set_state(STATE_FEEDBACK_NPS_COMMENT)
    await state_store.update_data(
        nps_user_id=str(user_id),
        nps_score=score,
        nps_kind=kind,
    )
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text=texts.get("msg_fb_thanks_for_rating", "Спасибо за оценку!"),
    )
    prompt = _get_nps_comment_prompt(score, kind, texts)
    await messenger_client.send_text(chat_id=incoming.chat_id, text=prompt)


@router.message_in_state(STATE_FEEDBACK_NPS_COMMENT)
async def handle_nps_comment(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle optional NPS comment; save and thank user."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    nps_service: NpsService = deps["nps_service"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    texts = await bot_texts_service.get_many(FEEDBACK_TEXTS_KEYS, locale)
    done_btn = texts.get("msg_fb_nps_done_btn", "Готово")

    text = (incoming.text or "").strip()
    if text == done_btn:
        text = ""

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await state_store.clear()
        return

    data = await state_store.get_data()
    await state_store.clear()
    user_id_raw = data.get("nps_user_id")
    score = data.get("nps_score")
    if not user_id_raw or score is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_session_expired_nps", ""),
        )
        return

    try:
        user_id = UUID(user_id_raw)
    except ValueError:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get(
                "msg_fb_error_try_again", "Ошибка. Попробуйте снова."
            ),
        )
        return

    if user.user_id != user_id:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_fb_insufficient_rights", "Недостаточно прав."),
        )
        return

    await nps_service.save(user_id, score, comment=text or None)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=texts.get("msg_fb_nps_thank", ""),
    )
