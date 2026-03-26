"""Max handlers for complaints."""

import logging
from typing import Any
from uuid import UUID

from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_complaint,
)
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.telegram.handlers.complaints import (
    _COMPLAINT_OTHER_INDEX,
    _COMPLAINT_REASONS,
)
from ugc_bot.domain.enums import MessengerType, UserStatus

logger = logging.getLogger(__name__)

router = MaxRouter()

STATE_COMPLAINT_REASON_TEXT = "complaint_reason_text"


async def _handle_advertiser_complaint_target(
    incoming: IncomingCallback,
    order_id: UUID,
    user_id: Any,
    messenger_client: Any,
    offer_response_service: OfferResponseService,
    user_role_service: UserRoleService,
    bot_texts_service: Any,
    state_store: Any,
    locale: str,
) -> None:
    """Show blogger selection keyboard when advertiser initiates a complaint."""
    responses = await offer_response_service.list_by_order(order_id)
    if not responses:
        msg_no_bloggers = await bot_texts_service.get(
            "msg_complaint_no_bloggers", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_no_bloggers,
        )
        return

    await state_store.update_data(
        order_id=str(order_id),
        blogger_ids=[str(r.blogger_id) for r in responses],
        reporter_id=str(user_id),
    )
    btn_complaint_tpl = (
        await bot_texts_service.get("btn_complaint", locale)
    ).strip() or "Пожаловаться на {name}"
    buttons: list[list[Button]] = []
    for i, response in enumerate(responses):
        blogger = await user_role_service.get_user_by_id(response.blogger_id)
        blogger_name = (
            blogger.username
            if blogger
            else f"Блогер {str(response.blogger_id)[:8]}"
        )
        buttons.append(
            [
                Button(
                    text=btn_complaint_tpl.format(name=blogger_name),
                    callback_data=f"complaint:{i}",
                )
            ]
        )
    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=buttons)
    msg_choose = await bot_texts_service.get(
        "msg_choose_blogger_complain", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_choose,
        keyboard=keyboard,
    )


async def _handle_blogger_complaint_target(
    incoming: IncomingCallback,
    order_id: UUID,
    advertiser_id: Any,
    user_id: Any,
    messenger_client: Any,
    offer_response_service: OfferResponseService,
    bot_texts_service: Any,
    state_store: Any,
    locale: str,
) -> None:
    """Show complaint reason keyboard when a blogger initiates a complaint."""
    responses = await offer_response_service.list_by_order(order_id)
    if not any(response.blogger_id == user_id for response in responses):
        msg_no_access = await bot_texts_service.get(
            "msg_no_access_order", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_no_access,
        )
        return

    await state_store.update_data(
        order_id=str(order_id),
        reported_id=str(advertiser_id),
        reporter_id=str(user_id),
    )

    buttons = [
        [Button(text=reason, callback_data=f"complaint_reason:{i}")]
        for i, reason in enumerate(_COMPLAINT_REASONS)
    ]
    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=buttons)

    msg_reason = await bot_texts_service.get(
        "msg_choose_complaint_reason", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_reason,
        keyboard=keyboard,
    )
    await state_store.set_state(STATE_COMPLAINT_REASON_TEXT)


@router.callback(
    lambda cb: bool(cb.data and cb.data.startswith("complaint_select:"))
)
async def select_complaint_target(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Show list of users to complain about for an order."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    order_service: OrderService = deps["order_service"]
    offer_response_service: OfferResponseService = deps[
        "offer_response_service"
    ]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    if not incoming.data:
        return

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    allow_msgs = await bot_texts_service.get_many(
        ["msg_user_not_found", "msg_complaint_blocked", "msg_complaint_pause"],
        locale,
    )
    if user is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=allow_msgs.get("msg_user_not_found", ""),
        )
        return
    if user.status == UserStatus.BLOCKED:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=allow_msgs.get("msg_complaint_blocked", ""),
        )
        return
    if user.status == UserStatus.PAUSE:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=allow_msgs.get("msg_complaint_pause", ""),
        )
        return

    parts = incoming.data.split(":")
    if len(parts) != 2:
        msg_invalid = await bot_texts_service.get(
            "msg_invalid_format_short", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id, text=msg_invalid
        )
        return

    _, order_id_raw = parts
    try:
        order_id = UUID(order_id_raw)
    except ValueError:
        msg_invalid_id = await bot_texts_service.get("msg_invalid_id", locale)
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_invalid_id,
        )
        return

    order = await order_service.get_order(order_id)
    if order is None:
        msg_not_found = await bot_texts_service.get(
            "msg_order_not_found", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id, text=msg_not_found
        )
        return

    if order.advertiser_id == user.user_id:
        await _handle_advertiser_complaint_target(
            incoming,
            order_id,
            user.user_id,
            messenger_client,
            offer_response_service,
            user_role_service,
            bot_texts_service,
            state_store,
            locale,
        )
    else:
        await _handle_blogger_complaint_target(
            incoming,
            order_id,
            order.advertiser_id,
            user.user_id,
            messenger_client,
            offer_response_service,
            bot_texts_service,
            state_store,
            locale,
        )

    await messenger_client.answer_callback(callback_id=incoming.callback_id)


@router.callback(lambda cb: bool(cb.data and cb.data.startswith("complaint:")))
async def start_complaint(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Start complaint creation process — show reason selection for blogger."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    if not incoming.data:
        return

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    allow_msgs = await bot_texts_service.get_many(
        ["msg_user_not_found", "msg_complaint_blocked", "msg_complaint_pause"],
        locale,
    )
    if user is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=allow_msgs.get("msg_user_not_found", ""),
        )
        return

    parts = incoming.data.split(":", 1)
    if len(parts) != 2:
        return
    try:
        blogger_idx = int(parts[1])
    except ValueError:
        return

    data = await state_store.get_data()
    blogger_ids: list[str] = data.get("blogger_ids", [])
    order_id_raw = data.get("order_id")
    reporter_id_raw = data.get("reporter_id")
    if (
        not order_id_raw
        or not reporter_id_raw
        or blogger_idx < 0
        or blogger_idx >= len(blogger_ids)
    ):
        msg_expired = await bot_texts_service.get("msg_session_expired", locale)
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id, text=msg_expired
        )
        return

    try:
        order_id = UUID(order_id_raw)
        reported_id = UUID(blogger_ids[blogger_idx])
    except ValueError:
        return

    await state_store.update_data(
        order_id=str(order_id),
        reported_id=str(reported_id),
        reporter_id=reporter_id_raw,
    )

    buttons = [
        [Button(text=reason, callback_data=f"complaint_reason:{i}")]
        for i, reason in enumerate(_COMPLAINT_REASONS)
    ]
    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=buttons)

    msg_reason = await bot_texts_service.get(
        "msg_choose_complaint_reason", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_reason,
        keyboard=keyboard,
    )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await state_store.set_state(STATE_COMPLAINT_REASON_TEXT)


@router.callback(
    lambda cb: bool(cb.data and cb.data.startswith("complaint_reason:"))
)
async def handle_complaint_reason(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Handle complaint reason selection."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    complaint_service: ComplaintService = deps["complaint_service"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    if not incoming.data:
        return

    data = await state_store.get_data()
    if not data:
        msg_expired = await bot_texts_service.get("msg_session_expired", locale)
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_expired,
        )
        return

    idx_raw = incoming.data.split("complaint_reason:", 1)[-1]
    try:
        reason_idx = int(idx_raw)
        reason = _COMPLAINT_REASONS[reason_idx]
    except (ValueError, IndexError):
        msg_invalid_reason = await bot_texts_service.get(
            "msg_invalid_reason", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id, text=msg_invalid_reason
        )
        return

    try:
        order_id = UUID(data["order_id"])
        reported_id = UUID(data["reported_id"])
        reporter_id = UUID(data["reporter_id"])
    except (ValueError, KeyError):
        msg_data_err = await bot_texts_service.get("msg_data_error", locale)
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_data_err,
        )
        return

    if reason_idx == _COMPLAINT_OTHER_INDEX:
        msg_describe = await bot_texts_service.get(
            "msg_describe_complaint", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_describe,
        )
        await state_store.update_data(reason=reason)
        await state_store.set_state(STATE_COMPLAINT_REASON_TEXT)
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return

    try:
        complaint = await complaint_service.create_complaint(
            reporter_id=reporter_id,
            reported_id=reported_id,
            order_id=order_id,
            reason=reason,
        )
        await notify_admins_about_complaint(
            complaint, messenger_client, user_role_service
        )
        msg_received = await bot_texts_service.get(
            "msg_complaint_received", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_received,
        )
        await state_store.clear()
    except ValueError as exc:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id, text=str(exc)
        )
    except Exception:
        logger.exception("Error creating complaint via callback")
        msg_error = await bot_texts_service.get("msg_error_later", locale)
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_error,
        )

    await messenger_client.answer_callback(callback_id=incoming.callback_id)


@router.message_in_state(STATE_COMPLAINT_REASON_TEXT)
async def handle_complaint_reason_text(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle text input for complaint reason (when 'Other' was selected)."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    complaint_service: ComplaintService = deps["complaint_service"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale: str = deps.get("locale", "ru")

    if not incoming.text:
        return

    data = await state_store.get_data()
    if not data:
        msg_expired = await bot_texts_service.get("msg_session_expired", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        return

    reason_text = incoming.text.strip()
    if not reason_text:
        msg_enter = await bot_texts_service.get(
            "msg_enter_complaint_reason", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_enter,
        )
        return

    try:
        order_id = UUID(data["order_id"])
        reported_id = UUID(data["reported_id"])
        reporter_id = UUID(data["reporter_id"])
    except (ValueError, KeyError):
        msg_data_err = await bot_texts_service.get("msg_data_error", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_data_err,
        )
        await state_store.clear()
        return

    base_reason = data.get("reason", "Другое")
    full_reason = (
        f"Другое: {reason_text}" if base_reason == "Другое" else reason_text
    )

    try:
        complaint = await complaint_service.create_complaint(
            reporter_id=reporter_id,
            reported_id=reported_id,
            order_id=order_id,
            reason=full_reason,
        )
        await notify_admins_about_complaint(
            complaint, messenger_client, user_role_service
        )
        msg_received = await bot_texts_service.get(
            "msg_complaint_received", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_received,
        )
        await state_store.clear()
    except ValueError as exc:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=str(exc),
        )
        await state_store.clear()
    except Exception:
        logger.exception("Error creating complaint via text reason")
        msg_error = await bot_texts_service.get("msg_error_later", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_error,
        )
        await state_store.clear()
