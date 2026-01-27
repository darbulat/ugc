"""Handlers for advertiser orders."""

from math import ceil

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType


router = Router()
_PAGE_SIZE = 5


@router.message(Command("my_orders"))
@router.message(lambda msg: (msg.text or "").strip() == "Мои заказы")
async def show_my_orders(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
) -> None:
    """Show orders for the current advertiser."""

    if message.from_user is None:
        return

    user = await user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await message.answer("Пользователь не найден. Выберите роль через /role.")
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is None:
        await message.answer(
            "Профиль рекламодателя не заполнен. Команда: /register_advertiser"
        )
        return

    orders = sorted(
        await order_service.list_by_advertiser(user.user_id),
        key=lambda item: item.created_at,
        reverse=True,
    )
    if not orders:
        await message.answer("У вас пока нет заказов. Создать заказ: /create_order")
        return

    text, keyboard = await _render_page(
        orders, page=1, offer_response_service=offer_response_service
    )
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("my_orders:")
)
async def paginate_orders(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
) -> None:
    """Handle pagination for orders list."""

    if callback.from_user is None:
        return

    user = await user_role_service.get_user(
        external_id=str(callback.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await callback.answer("Пользователь не найден.")
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is None:
        await callback.answer("Профиль рекламодателя не заполнен.")
        return

    raw = callback.data.split("my_orders:", 1)[-1] if callback.data else ""
    try:
        page = int(raw)
    except ValueError:
        page = 1

    orders = sorted(
        await order_service.list_by_advertiser(user.user_id),
        key=lambda item: item.created_at,
        reverse=True,
    )
    text, keyboard = await _render_page(
        orders, page=page, offer_response_service=offer_response_service
    )
    message = callback.message
    if message and hasattr(message, "edit_text"):
        await message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


async def _render_page(
    orders, page: int, offer_response_service: OfferResponseService
) -> tuple[str, InlineKeyboardMarkup]:
    """Render paginated orders list."""

    total_pages = max(1, ceil(len(orders) / _PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * _PAGE_SIZE
    end = start + _PAGE_SIZE
    slice_orders = orders[start:end]

    lines = [f"Ваши заказы (страница {page}/{total_pages}):"]
    buttons_rows: list[list[InlineKeyboardButton]] = []

    for order in slice_orders:
        lines.append(
            "\n".join(
                [
                    f"ID: {order.order_id}",
                    f"Статус: {order.status.value}",
                    f"Ссылка: {order.product_link}",
                    f"Цена: {order.price}",
                    f"Блогеров нужно: {order.bloggers_needed}",
                ]
            )
        )
        # Add complaint button for closed orders (when contacts are sent)
        if order.status.value == "closed":
            # Get bloggers who responded to this order
            responses = await offer_response_service.response_repo.list_by_order(
                order.order_id
            )
            if responses:
                # For advertiser: show button to select blogger to complain about
                buttons_rows.append(
                    [
                        InlineKeyboardButton(
                            text="⚠️ Пожаловаться",
                            callback_data=f"complaint_select:{order.order_id}",
                        )
                    ]
                )

    # Pagination buttons
    nav_buttons: list[InlineKeyboardButton] = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"my_orders:{page - 1}")
        )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="Вперед ➡️", callback_data=f"my_orders:{page + 1}")
        )
    if nav_buttons:
        buttons_rows.append(nav_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons_rows)
    return "\n\n".join(lines), keyboard
