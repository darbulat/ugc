"""Handlers for complaints."""

from uuid import UUID

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_complaint,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

router = Router()


class ComplaintStates(StatesGroup):
    """FSM states for complaint creation."""

    waiting_for_reason = State()


_COMPLAINT_REASONS = [
    "Мошенничество",
    "Некачественное выполнение работы",
    "Нарушение сроков",
    "Некорректное поведение",
    "Другое",
]


@router.callback_query(
    lambda callback: (
        callback.data and callback.data.startswith("complaint_select:")
    )
)
async def select_complaint_target(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Show list of users to complain about for an order."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    locale = user_locale
    if not incoming.data:
        return

    allow_msgs = await bot_texts_service.get_many(
        ["msg_user_not_found", "msg_complaint_blocked", "msg_complaint_pause"],
        locale,
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_user_not_found", ""),
        blocked_msg=allow_msgs.get("msg_complaint_blocked", ""),
        pause_msg=allow_msgs.get("msg_complaint_pause", ""),
    )
    if user is None:
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

    # Verify user has access to this order
    if order.advertiser_id == user.user_id:
        # Advertiser: show list of bloggers who responded
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

        buttons: list[list[Button]] = []
        for response in responses:
            blogger = await user_role_service.get_user_by_id(
                response.blogger_id
            )
            blogger_name = (
                blogger.username
                if blogger
                else f"Блогер {str(response.blogger_id)[:8]}"
            )
            btn_complaint_tpl = (
                await bot_texts_service.get("btn_complaint", locale)
            ).strip() or "Пожаловаться на {name}"
            buttons.append(
                [
                    Button(
                        text=btn_complaint_tpl.format(name=blogger_name),
                        callback_data=f"complaint:{order_id}:{response.blogger_id}",
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
    else:
        # Blogger: complain about advertiser
        responses = await offer_response_service.list_by_order(order_id)
        if not any(
            response.blogger_id == user.user_id for response in responses
        ):
            msg_no_access = await bot_texts_service.get(
                "msg_no_access_order", locale
            )
            await messenger_client.answer_callback(
                callback_id=incoming.callback_id,
                text=msg_no_access,
            )
            return

        # Store complaint data in state
        await state_store.update_data(
            order_id=str(order_id),
            reported_id=str(order.advertiser_id),
            reporter_id=str(user.user_id),
        )

        # Show reason selection keyboard
        buttons = [
            [Button(text=reason, callback_data=f"complaint_reason:{reason}")]
            for reason in _COMPLAINT_REASONS
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
        await state_store.set_state(ComplaintStates.waiting_for_reason.state)

    await messenger_client.answer_callback(callback_id=incoming.callback_id)


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("complaint:")
)
async def start_complaint(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start complaint creation process."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    locale = user_locale
    if not incoming.data:
        return

    allow_msgs = await bot_texts_service.get_many(
        ["msg_user_not_found", "msg_complaint_blocked", "msg_complaint_pause"],
        locale,
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_user_not_found", ""),
        blocked_msg=allow_msgs.get("msg_complaint_blocked", ""),
        pause_msg=allow_msgs.get("msg_complaint_pause", ""),
    )
    if user is None:
        return

    parts = incoming.data.split(":")
    if len(parts) != 3:
        msg_invalid = await bot_texts_service.get(
            "msg_invalid_format_short", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id, text=msg_invalid
        )
        return

    _, order_id_raw, reported_id_raw = parts

    try:
        order_id = UUID(order_id_raw)
        reported_id = UUID(reported_id_raw)
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

    # Verify user has access to this order
    if order.advertiser_id != user.user_id:
        # Check if user is a blogger who responded to this order
        responses = await offer_response_service.list_by_order(order_id)
        if not any(
            response.blogger_id == user.user_id for response in responses
        ):
            msg_no_access = await bot_texts_service.get(
                "msg_no_access_order", locale
            )
            await messenger_client.answer_callback(
                callback_id=incoming.callback_id,
                text=msg_no_access,
            )
            return

    # Verify reported_id is valid (either advertiser or blogger from this order)
    if reported_id != order.advertiser_id:
        responses = await offer_response_service.list_by_order(order_id)
        if not any(
            response.blogger_id == reported_id for response in responses
        ):
            msg_invalid_user = await bot_texts_service.get(
                "msg_invalid_uuid", locale
            )
            await messenger_client.answer_callback(
                callback_id=incoming.callback_id,
                text=msg_invalid_user,
            )
            return

    # Store complaint data in state
    await state_store.update_data(
        order_id=str(order_id),
        reported_id=str(reported_id),
        reporter_id=str(user.user_id),
    )

    # Show reason selection keyboard
    buttons = [
        [Button(text=reason, callback_data=f"complaint_reason:{reason}")]
        for reason in _COMPLAINT_REASONS
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
    await state_store.set_state(ComplaintStates.waiting_for_reason.state)


@router.callback_query(
    lambda callback: (
        callback.data and callback.data.startswith("complaint_reason:")
    )
)
async def handle_complaint_reason(
    callback: CallbackQuery,
    state: FSMContext,
    complaint_service: ComplaintService,
    order_service: OrderService,
    user_role_service: UserRoleService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle complaint reason selection."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    locale = user_locale
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

    reason = incoming.data.split("complaint_reason:", 1)[-1]
    if reason not in _COMPLAINT_REASONS:
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

    # If "Другое" is selected, ask for text input
    if reason == "Другое":
        msg_describe = await bot_texts_service.get(
            "msg_describe_complaint", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_describe,
        )
        await state_store.update_data(reason=reason)
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return

    # Create complaint with selected reason
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
        msg_error = await bot_texts_service.get("msg_error_later", locale)
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg_error,
        )

    await messenger_client.answer_callback(callback_id=incoming.callback_id)


@router.message(ComplaintStates.waiting_for_reason)
async def handle_complaint_reason_text(
    message: Message,
    state: FSMContext,
    complaint_service: ComplaintService,
    user_role_service: UserRoleService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle text input for complaint reason."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
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

    # Use "Другое: " prefix if "Другое" was selected
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
        msg_error = await bot_texts_service.get("msg_error_later", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_error,
        )
        await state_store.clear()
