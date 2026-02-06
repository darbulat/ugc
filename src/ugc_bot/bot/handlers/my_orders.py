"""Handlers for advertiser and blogger orders."""

from datetime import datetime
from math import ceil
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import MY_ORDERS_BUTTON_TEXT
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
)
from ugc_bot.domain.entities import Order, OrderResponse
from ugc_bot.domain.enums import OrderStatus, OrderType

router = Router()
ORDER_STATUS_LABELS = {
    OrderStatus.NEW: "Создан",
    OrderStatus.PENDING_MODERATION: "На модерации",
    OrderStatus.ACTIVE: "Активен",
    OrderStatus.CLOSED: "Завершён",
}


def _format_price(price: float) -> str:
    """Format price with space as thousands separator and ruble sign."""
    return f"{int(price):,}".replace(",", " ") + " ₽"


def _format_date(dt: Optional[datetime]) -> str:
    """Format date as DD.MM.YYYY or em dash if None."""
    if dt is None:
        return "—"
    return dt.strftime("%d.%m.%Y")


def _format_order_type(order: Order) -> str:
    """Format order type for display."""
    if order.order_type == OrderType.UGC_PLUS_PLACEMENT:
        return "UGC + размещение"
    return "UGC-видео для бренда"


def _format_price_and_barter(order: Order) -> list[str]:
    """Return lines for price and/or barter (0-2 lines)."""
    result: list[str] = []
    if order.price > 0:
        result.append(f"Стоимость 1 UGC: {_format_price(order.price)}")
    if order.barter_description:
        result.append(f"Бартер: {order.barter_description}")
    return result


_PAGE_SIZE = 5
_MY_ORDERS_CALLBACK_PREFIX = "my_orders:"
_MY_ORDERS_BLOGGER_CALLBACK_PREFIX = "my_orders_blogger:"


@router.message(Command("my_orders"))
@router.message(lambda msg: (msg.text or "").strip() == MY_ORDERS_BUTTON_TEXT)
async def show_my_orders(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
) -> None:
    """Show orders: advertiser's created or blogger's responded."""

    user = await get_user_and_ensure_allowed(
        message,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Выберите роль через /role.",
        blocked_msg="Заблокированные не могут просматривать заказы.",
        pause_msg="На паузе не могут просматривать заказы.",
    )
    if user is None:
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    blogger = await profile_service.get_blogger_profile(user.user_id)

    if advertiser is not None:
        orders = sorted(
            await order_service.list_by_advertiser(user.user_id),
            key=lambda item: item.created_at,
            reverse=True,
        )
        if not orders:
            await message.answer("У вас пока нет заказов. /create_order")
            return
        text, keyboard = await _render_page(
            orders, page=1, offer_response_service=offer_response_service
        )
        await message.answer(text, reply_markup=keyboard)
        return

    if blogger is not None:
        responses = await offer_response_service.list_by_blogger(user.user_id)
        order_responses = []
        for resp in sorted(
            responses, key=lambda r: r.responded_at, reverse=True
        ):
            order = await order_service.get_order(resp.order_id)
            if order is not None:
                order_responses.append((order, resp))
        if not order_responses:
            await message.answer(
                "Вы пока не откликались. Предложения приходят в бот."
            )
            return
        text, keyboard = _render_blogger_orders_page(order_responses, page=1)
        await message.answer(text, reply_markup=keyboard)
        return

    await message.answer(
        "Заполните профиль (/register_advertiser или /register), "
        "чтобы видеть заказы."
    )


@router.callback_query(
    lambda c: c.data
    and (
        c.data.startswith(_MY_ORDERS_CALLBACK_PREFIX)
        or c.data.startswith(_MY_ORDERS_BLOGGER_CALLBACK_PREFIX)
    )
)
async def paginate_orders(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
) -> None:
    """Handle pagination for advertiser and blogger orders."""

    user = await get_user_and_ensure_allowed_callback(
        callback,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Заблокированные не могут просматривать заказы.",
        pause_msg="Пользователи на паузе не могут просматривать заказы.",
    )
    if user is None:
        return

    data = callback.data or ""
    if data.startswith(_MY_ORDERS_BLOGGER_CALLBACK_PREFIX):
        raw = data.split(_MY_ORDERS_BLOGGER_CALLBACK_PREFIX, 1)[-1]
        blogger = await profile_service.get_blogger_profile(user.user_id)
        if blogger is None:
            await callback.answer("Профиль блогера не заполнен.")
            return
        try:
            page = int(raw)
        except ValueError:
            page = 1
        responses = await offer_response_service.list_by_blogger(user.user_id)
        order_responses = []
        for resp in sorted(
            responses, key=lambda r: r.responded_at, reverse=True
        ):
            order = await order_service.get_order(resp.order_id)
            if order is not None:
                order_responses.append((order, resp))
        text, keyboard = _render_blogger_orders_page(order_responses, page=page)
    else:
        raw = data.split(_MY_ORDERS_CALLBACK_PREFIX, 1)[-1]
        advertiser = await profile_service.get_advertiser_profile(user.user_id)
        if advertiser is None:
            await callback.answer("Профиль рекламодателя не заполнен.")
            return
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

    for idx, order in enumerate(slice_orders):
        # Нумерация по дате создания: 1 = первый созданный (самый старый)
        creation_number = len(orders) - start - idx
        matched_count = await offer_response_service.count_by_order(
            order.order_id
        )
        status_label = ORDER_STATUS_LABELS.get(order.status, order.status.value)
        order_lines = [
            f"№ {creation_number}",
            f"Статус: {status_label}",
            f"Креаторов: {order.bloggers_needed}",
            f"Подобрано: {matched_count} / {order.bloggers_needed}",
            *_format_price_and_barter(order),
            f"Дата создания: {_format_date(order.created_at)}",
            f"Дата завершения: {_format_date(order.completed_at)}",
            f"Ссылка на проект: {order.product_link}",
        ]
        lines.append("\n".join(order_lines))
        # Add complaint button for closed orders (when contacts are sent)
        if order.status == OrderStatus.CLOSED and matched_count > 0:
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
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"{_MY_ORDERS_CALLBACK_PREFIX}{page - 1}",
            )
        )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=f"{_MY_ORDERS_CALLBACK_PREFIX}{page + 1}",
            )
        )
    if nav_buttons:
        buttons_rows.append(nav_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons_rows)
    return "\n\n".join(lines), keyboard


def _render_blogger_orders_page(
    order_responses: list[tuple[Order, OrderResponse]],
    page: int = 1,
) -> tuple[str, InlineKeyboardMarkup]:
    """Render paginated list of orders the blogger responded to."""

    total_pages = max(1, ceil(len(order_responses) / _PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * _PAGE_SIZE
    end = start + _PAGE_SIZE
    slice_pairs = order_responses[start:end]

    # Нумерация по дате создания заказа: 1 = первый созданный
    orders_sorted_by_created = sorted(
        order_responses, key=lambda pair: pair[0].created_at
    )
    order_id_to_number = {
        order.order_id: idx + 1
        for idx, (order, _) in enumerate(orders_sorted_by_created)
    }

    lines = [
        f"Заказы, на которые вы откликнулись (страница {page}/{total_pages}):"
    ]
    buttons_rows: list[list[InlineKeyboardButton]] = []

    for order, _response in slice_pairs:
        creation_number = order_id_to_number.get(order.order_id, 0)
        status_label = ORDER_STATUS_LABELS.get(order.status, order.status.value)
        order_lines = [
            f"№ {creation_number}",
            f"Статус: {status_label}",
            f"Формат: {_format_order_type(order)}",
            *_format_price_and_barter(order),
            f"Ссылка на проект: {order.product_link}",
        ]
        lines.append("\n".join(order_lines))

    nav_buttons: list[InlineKeyboardButton] = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"{_MY_ORDERS_BLOGGER_CALLBACK_PREFIX}{page - 1}",
            )
        )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=f"{_MY_ORDERS_BLOGGER_CALLBACK_PREFIX}{page + 1}",
            )
        )
    if nav_buttons:
        buttons_rows.append(nav_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons_rows)
    return "\n\n".join(lines), keyboard
