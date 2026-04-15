"""Telegram handlers for blogger rating flow."""

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

from ugc_bot.application.errors import (
    InvalidRatingScoreError,
    RatingAlreadyExistsError,
)
from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
from ugc_bot.application.services.manager_service import ManagerService
from ugc_bot.application.services.user_role_service import UserRoleService
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
                    callback_data=f"brs:{order_id}:{blogger_id}:{score}",
                )
                for score in range(1, 6)
            ]
        ]
    )


def _skip_comment_keyboard() -> InlineKeyboardMarkup:
    """Create inline keyboard with skip comment action."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пропустить",
                    callback_data="brc:skip",
                )
            ]
        ]
    )


async def send_order_rating_prompt(
    message: Message,
    order_id: UUID,
    blogger_id: UUID,
) -> None:
    """Send rating prompt with stars."""
    await message.answer(
        "Оцените работу креатора от 1 до 5:",
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


@router.callback_query(lambda c: c.data and c.data.startswith("brs:"))
async def handle_rating_score(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Store selected score and ask for optional comment."""
    if callback.data is None:
        return
    _, order_id_raw, blogger_id_raw, score_raw = callback.data.split(":")
    await state.set_state(RatingStates.waiting_comment)
    await state.update_data(
        order_id=order_id_raw,
        blogger_id=blogger_id_raw,
        score=int(score_raw),
    )
    if callback.message is not None:
        await callback.message.answer(
            "Напишите комментарий или нажмите «Пропустить».",
            reply_markup=_skip_comment_keyboard(),
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


@router.message(RatingStates.waiting_comment)
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
        await _answer_event(event, "Сессия оценки истекла. Попробуйте снова.")
        return

    from_user = event.from_user
    if from_user is None:
        return
    user = await user_role_service.get_user(
        external_id=str(from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await _answer_event(event, "Пользователь не найден.")
        return

    order_id = UUID(order_id_raw)
    blogger_id = UUID(blogger_id_raw)
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
        )
    except RatingAlreadyExistsError:
        await _answer_event(event, "Оценка для этого заказа уже сохранена.")
        return
    except InvalidRatingScoreError:
        await _answer_event(event, "Оценка должна быть от 1 до 5.")
        return

    await _answer_event(event, "Спасибо, оценка сохранена.")


async def _answer_event(event: Message | CallbackQuery, text: str) -> None:
    """Send a message for either callback or plain message event."""
    if isinstance(event, CallbackQuery):
        if event.message is not None:
            await event.message.answer(text)
        await event.answer()
        return
    await event.answer(text)
