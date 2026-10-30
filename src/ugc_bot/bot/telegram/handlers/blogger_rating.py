"""Telegram handlers for blogger rating flow."""

from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ugc_bot.application.errors import (
    InvalidRatingScoreError,
    RatingAlreadyExistsError,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
from ugc_bot.application.services.manager_service import ManagerService
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.rating_entry import (
    RATING_MENU,
    RATING_ORDER,
    RATING_PARTICIPANT,
    compact_id,
    eligible_rating_participants,
    expand_id,
    rating_text,
    show_rating_orders,
)
from ugc_bot.bot.telegram.handlers.utils import resolve_messenger_dependencies
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.domain.enums import MessengerType, RaterRole

router = Router()


class RatingStates(StatesGroup):
    """FSM states for rating comment collection."""

    waiting_comment = State()


def _rating_keyboard(order_id: UUID, blogger_id: UUID) -> InlineKeyboardMarkup:
    """Create 1-5 star inline keyboard for rating."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{score} ⭐",
                    callback_data=f"br2:{compact_id(order_id)}:{compact_id(blogger_id)}:{score}",
                )
                for score in range(1, 6)
            ]
        ]
    )


def _skip_comment_keyboard(locale: str = "ru") -> InlineKeyboardMarkup:
    """Create inline keyboard with skip comment action."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=rating_text(locale, "rating_skip"),
                    callback_data="brc:skip",
                )
            ]
        ]
    )


async def send_order_rating_prompt(
    message: Message,
    order_id: UUID,
    blogger_id: UUID,
    locale: str = "ru",
) -> None:
    """Send rating prompt with stars."""
    await message.answer(
        rating_text(locale, "rating_prompt"),
        reply_markup=_rating_keyboard(order_id, blogger_id),
    )


async def _resolve_rater_role(
    user_id: UUID,
    order_id: UUID,
    user_role_service: UserRoleService,
    manager_service: ManagerService,
) -> RaterRole:
    """Resolve role for rating action."""
    user = await user_role_service.get_user_by_id(user_id)
    if user is not None and user.admin:
        return RaterRole.ADMIN
    if await manager_service.is_manager_for_order(user_id, order_id):
        return RaterRole.MANAGER
    return RaterRole.ADVERTISER


def decode_rating_callback(data: str) -> tuple[UUID, UUID, int]:
    prefix, order, blogger, score = data.split(":")
    if prefix == "br2":
        result = (expand_id(order), expand_id(blogger), int(score))
        if not 1 <= result[2] <= 5:
            raise ValueError("rating_callback_invalid")
        return result
    if prefix == "brs":
        return UUID(order), UUID(blogger), int(score)
    raise ValueError("rating_callback_invalid")


@router.message(Command("rate_order"))
async def rating_orders_command(
    message: Message,
    user_role_service: UserRoleService,
    order_service: OrderService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    await show_rating_orders(
        event_adapter.from_message(message),
        messenger_client,
        user_role_service,
        order_service,
        user_locale,
    )


@router.callback_query(lambda c: c.data == RATING_MENU)
async def rating_orders_callback(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    order_service: OrderService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await show_rating_orders(
        incoming,
        messenger_client,
        user_role_service,
        order_service,
        user_locale,
    )


@router.callback_query(
    lambda c: bool(c.data and c.data.startswith(RATING_ORDER))
)
async def rating_order_callback(
    callback: CallbackQuery,
    blogger_rating_service: BloggerRatingService,
    user_role_service: UserRoleService,
    user_locale: str = "ru",
) -> None:
    try:
        order_id = expand_id((callback.data or "")[len(RATING_ORDER) :])
        incoming = resolve_messenger_dependencies(callback, None, None)[
            1
        ].from_callback(callback)
        participants = await eligible_rating_participants(
            incoming, user_role_service, blogger_rating_service, order_id
        )
    except (ValueError, PermissionError):
        await _answer_event(
            callback, rating_text(user_locale, "msg_rating_work_required")
        )
        return
    if callback.message is not None:
        await callback.message.answer(
            rating_text(
                user_locale,
                "rating_choose_creator"
                if participants
                else "rating_no_completed",
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=item["display_name"][:50],
                            callback_data=f"{RATING_PARTICIPANT}{compact_id(order_id)}:{compact_id(UUID(item['blogger_id']))}",
                        )
                    ]
                    for item in participants
                ]
            )
            if participants
            else None,
        )
    await callback.answer()


@router.callback_query(
    lambda c: bool(c.data and c.data.startswith(RATING_PARTICIPANT))
)
async def rating_participant_callback(
    callback: CallbackQuery,
    blogger_rating_service: BloggerRatingService,
    user_role_service: UserRoleService,
    user_locale: str = "ru",
) -> None:
    try:
        _, order, blogger = (callback.data or "").split(":")
        order_id, blogger_id = expand_id(order), expand_id(blogger)
        incoming = resolve_messenger_dependencies(callback, None, None)[
            1
        ].from_callback(callback)
        participants = await eligible_rating_participants(
            incoming, user_role_service, blogger_rating_service, order_id
        )
        if not any(
            item["blogger_id"] == str(blogger_id) for item in participants
        ):
            raise PermissionError("rating_access_denied")
    except (ValueError, PermissionError):
        await _answer_event(
            callback, rating_text(user_locale, "msg_rating_work_required")
        )
        return
    if isinstance(callback.message, Message):
        await send_order_rating_prompt(
            callback.message, order_id, blogger_id, user_locale
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith(("brs:", "br2:")))
async def handle_rating_score(
    callback: CallbackQuery,
    state: FSMContext,
    blogger_rating_service: BloggerRatingService | None = None,
    user_role_service: UserRoleService | None = None,
    user_locale: str = "ru",
) -> None:
    """Store selected score and ask for optional comment."""
    if callback.data is None:
        return
    try:
        order_id, blogger_id, score = decode_rating_callback(callback.data)
        if callback.data.startswith("br2:"):
            if blogger_rating_service is None or user_role_service is None:
                raise PermissionError("rating_access_denied")
            incoming = resolve_messenger_dependencies(callback, None, None)[
                1
            ].from_callback(callback)
            participants = await eligible_rating_participants(
                incoming, user_role_service, blogger_rating_service, order_id
            )
            if not any(
                item["blogger_id"] == str(blogger_id) for item in participants
            ):
                raise PermissionError("rating_access_denied")
    except (ValueError, PermissionError):
        await _answer_event(
            callback, rating_text(user_locale, "msg_rating_work_required")
        )
        return
    await state.set_state(RatingStates.waiting_comment)
    await state.update_data(
        order_id=str(order_id),
        blogger_id=str(blogger_id),
        score=score,
    )
    if user_locale != "ru":
        await state.update_data(rating_locale=user_locale)
    if callback.message is not None:
        await callback.message.answer(
            rating_text(user_locale, "rating_comment"),
            reply_markup=_skip_comment_keyboard(user_locale),
        )
    await callback.answer()


@router.callback_query(
    RatingStates.waiting_comment, lambda c: c.data == "brc:skip"
)
async def handle_skip_comment(
    callback: CallbackQuery,
    state: FSMContext,
    blogger_rating_service: BloggerRatingService,
    user_role_service: UserRoleService,
    manager_service: ManagerService,
) -> None:
    """Save rating without comment."""
    await _save_rating_from_state(
        callback,
        state,
        blogger_rating_service,
        user_role_service,
        manager_service,
        comment=None,
    )


@router.message(
    RatingStates.waiting_comment,
    lambda message: not (message.text or "").startswith("/"),
)
async def handle_rating_comment(
    message: Message,
    state: FSMContext,
    blogger_rating_service: BloggerRatingService,
    user_role_service: UserRoleService,
    manager_service: ManagerService,
) -> None:
    """Save rating with comment."""
    await _save_rating_from_state(
        message,
        state,
        blogger_rating_service,
        user_role_service,
        manager_service,
        comment=(message.text or "").strip() or None,
    )


async def _save_rating_from_state(
    event: Message | CallbackQuery,
    state: FSMContext,
    blogger_rating_service: BloggerRatingService,
    user_role_service: UserRoleService,
    manager_service: ManagerService,
    comment: str | None,
) -> None:
    """Persist rating from FSM data and send user feedback."""
    data = await state.get_data()
    await state.clear()
    order_id_raw = data.get("order_id")
    blogger_id_raw = data.get("blogger_id")
    score = data.get("score")
    if not order_id_raw or not blogger_id_raw or score is None:
        await _answer_event(
            event,
            rating_text(data.get("rating_locale", "ru"), "rating_expired"),
        )
        return

    from_user = event.from_user
    if from_user is None:
        return
    user = await user_role_service.get_user(
        external_id=str(from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await _answer_event(
            event,
            rating_text(data.get("rating_locale", "ru"), "rating_user_missing"),
        )
        return

    locale = (
        getattr(user, "language", None) or data.get("rating_locale") or "ru"
    )
    try:
        order_id = UUID(order_id_raw)
        blogger_id = UUID(blogger_id_raw)
    except ValueError:
        await _answer_event(event, rating_text(locale, "rating_expired"))
        return
    rater_role = await _resolve_rater_role(
        user.user_id, order_id, user_role_service, manager_service
    )
    try:
        await blogger_rating_service.rate_blogger(
            blogger_id=blogger_id,
            order_id=order_id,
            rater_id=user.user_id,
            rater_role=rater_role,
            score=int(score),
            comment=comment,
            principal=AuthenticatedMessengerPrincipal(
                user.user_id, "telegram", str(from_user.id)
            ),
        )
    except RatingAlreadyExistsError:
        await _answer_event(event, rating_text(locale, "rating_exists"))
        return
    except InvalidRatingScoreError:
        await _answer_event(event, rating_text(locale, "rating_invalid_score"))
        return

    except (ValueError, PermissionError):
        locale = (
            getattr(user, "language", None) or data.get("rating_locale") or "ru"
        )
        message = DEFAULT_TEXTS.get(locale, DEFAULT_TEXTS["ru"])[
            "msg_rating_work_required"
        ]
        await _answer_event(event, message)
        return

    await _answer_event(event, rating_text(locale, "rating_saved"))


async def _answer_event(event: Message | CallbackQuery, text: str) -> None:
    """Send a message for either callback or plain message event."""
    if isinstance(event, CallbackQuery):
        if event.message is not None:
            await event.message.answer(text)
        await event.answer()
        return
    await event.answer(text)
