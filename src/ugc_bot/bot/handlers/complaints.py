"""Handlers for complaints."""

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

from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType


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
    lambda callback: callback.data and callback.data.startswith("complaint_select:")
)
async def select_complaint_target(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
    profile_service: ProfileService,
) -> None:
    """Show list of users to complain about for an order."""

    if callback.from_user is None or not callback.data:
        return

    user = await user_role_service.get_user(
        external_id=str(callback.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await callback.answer("Пользователь не найден.")
        return

    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Неверный формат.")
        return

    _, order_id_raw = parts

    try:
        order_id = UUID(order_id_raw)
    except ValueError:
        await callback.answer("Неверный формат идентификатора.")
        return

    order = await order_service.get_order(order_id)
    if order is None:
        await callback.answer("Заказ не найден.")
        return

    # Verify user has access to this order
    if order.advertiser_id == user.user_id:
        # Advertiser: show list of bloggers who responded
        responses = await offer_response_service.list_by_order(order_id)
        if not responses:
            await callback.answer("Нет блогеров для жалобы.")
            return

        buttons = []
        for response in responses:
            blogger = await user_role_service.get_user_by_id(response.blogger_id)
            blogger_name = (
                blogger.username
                if blogger
                else f"Блогер {str(response.blogger_id)[:8]}"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"Пожаловаться на {blogger_name}",
                        callback_data=f"complaint:{order_id}:{response.blogger_id}",
                    )
                ]
            )
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.answer(  # type: ignore[union-attr]
            "Выберите блогера, на которого хотите пожаловаться:",
            reply_markup=keyboard,
        )
    else:
        # Blogger: complain about advertiser
        responses = await offer_response_service.list_by_order(order_id)
        if not any(response.blogger_id == user.user_id for response in responses):
            await callback.answer("У вас нет доступа к этому заказу.")
            return

        # Blogger: complain about advertiser
        # Verify access
        responses = await offer_response_service.list_by_order(order_id)
        if not any(response.blogger_id == user.user_id for response in responses):
            await callback.answer("У вас нет доступа к этому заказу.")
            return

        # Store complaint data in state
        await state.update_data(
            order_id=str(order_id),
            reported_id=str(order.advertiser_id),
            reporter_id=str(user.user_id),
        )

        # Show reason selection keyboard
        buttons = [
            [
                InlineKeyboardButton(
                    text=reason, callback_data=f"complaint_reason:{reason}"
                )
            ]
            for reason in _COMPLAINT_REASONS
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.answer(  # type: ignore[union-attr]
            "Выберите причину жалобы:",
            reply_markup=keyboard,
        )
        await state.set_state(ComplaintStates.waiting_for_reason)

    await callback.answer()


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("complaint:")
)
async def start_complaint(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
) -> None:
    """Start complaint creation process."""

    if callback.from_user is None or not callback.data:
        return

    user = await user_role_service.get_user(
        external_id=str(callback.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await callback.answer("Пользователь не найден.")
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Неверный формат.")
        return

    _, order_id_raw, reported_id_raw = parts

    try:
        order_id = UUID(order_id_raw)
        reported_id = UUID(reported_id_raw)
    except ValueError:
        await callback.answer("Неверный формат идентификатора.")
        return

    order = await order_service.get_order(order_id)
    if order is None:
        await callback.answer("Заказ не найден.")
        return

    # Verify user has access to this order
    if order.advertiser_id != user.user_id:
        # Check if user is a blogger who responded to this order
        responses = await offer_response_service.list_by_order(order_id)
        if not any(response.blogger_id == user.user_id for response in responses):
            await callback.answer("У вас нет доступа к этому заказу.")
            return

    # Verify reported_id is valid (either advertiser or blogger from this order)
    if reported_id != order.advertiser_id:
        responses = await offer_response_service.list_by_order(order_id)
        if not any(response.blogger_id == reported_id for response in responses):
            await callback.answer("Неверный идентификатор пользователя.")
            return

    # Store complaint data in state
    await state.update_data(
        order_id=str(order_id),
        reported_id=str(reported_id),
        reporter_id=str(user.user_id),
    )

    # Show reason selection keyboard
    buttons = [
        [InlineKeyboardButton(text=reason, callback_data=f"complaint_reason:{reason}")]
        for reason in _COMPLAINT_REASONS
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer(  # type: ignore[union-attr]
        "Выберите причину жалобы:",
        reply_markup=keyboard,
    )
    await callback.answer()
    await state.set_state(ComplaintStates.waiting_for_reason)


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("complaint_reason:")
)
async def handle_complaint_reason(
    callback: CallbackQuery,
    state: FSMContext,
    complaint_service: ComplaintService,
    order_service: OrderService,
) -> None:
    """Handle complaint reason selection."""

    if callback.from_user is None or not callback.data:
        return

    data = await state.get_data()
    if not data:
        await callback.answer("Сессия истекла. Начните заново.")
        return

    reason = callback.data.split("complaint_reason:", 1)[-1]
    if reason not in _COMPLAINT_REASONS:
        await callback.answer("Неверная причина.")
        return

    try:
        order_id = UUID(data["order_id"])
        reported_id = UUID(data["reported_id"])
        reporter_id = UUID(data["reporter_id"])
    except (ValueError, KeyError):
        await callback.answer("Ошибка обработки данных.")
        return

    # If "Другое" is selected, ask for text input
    if reason == "Другое":
        await callback.message.answer(  # type: ignore[union-attr]
            "Опишите причину жалобы:",
        )
        await state.update_data(reason=reason)
        await callback.answer()
        return

    # Create complaint with selected reason
    try:
        await complaint_service.create_complaint(
            reporter_id=reporter_id,
            reported_id=reported_id,
            order_id=order_id,
            reason=reason,
        )
        await callback.message.answer(  # type: ignore[union-attr]
            "Жалоба успешно подана. Администратор рассмотрит её в ближайшее время."
        )
        await state.clear()
    except ValueError as e:
        await callback.answer(str(e))
    except Exception:
        await callback.answer("Произошла ошибка. Попробуйте позже.")

    await callback.answer()


@router.message(ComplaintStates.waiting_for_reason)
async def handle_complaint_reason_text(
    message: Message,
    state: FSMContext,
    complaint_service: ComplaintService,
) -> None:
    """Handle text input for complaint reason."""

    if message.from_user is None or not message.text:
        return

    data = await state.get_data()
    if not data:
        await message.answer("Сессия истекла. Начните заново.")
        return

    reason_text = message.text.strip()
    if not reason_text:
        await message.answer("Пожалуйста, введите причину жалобы.")
        return

    try:
        order_id = UUID(data["order_id"])
        reported_id = UUID(data["reported_id"])
        reporter_id = UUID(data["reporter_id"])
    except (ValueError, KeyError):
        await message.answer("Ошибка обработки данных.")
        await state.clear()
        return

    # Use "Другое: " prefix if "Другое" was selected
    base_reason = data.get("reason", "Другое")
    if base_reason == "Другое":
        full_reason = f"Другое: {reason_text}"
    else:
        full_reason = reason_text

    try:
        await complaint_service.create_complaint(
            reporter_id=reporter_id,
            reported_id=reported_id,
            order_id=order_id,
            reason=full_reason,
        )
        await message.answer(
            "Жалоба успешно подана. Администратор рассмотрит её в ближайшее время."
        )
        await state.clear()
    except ValueError as e:
        await message.answer(str(e))
        await state.clear()
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")
        await state.clear()
