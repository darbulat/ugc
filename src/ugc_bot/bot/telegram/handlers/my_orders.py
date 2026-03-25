"""Handlers for advertiser and blogger orders."""

from datetime import datetime
from math import ceil
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.messenger.dto import (
    Button,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.ports import CountryRepository
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.filters import TextEqualsKey
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_PROFILE_AGREE,
    CALLBACK_PROFILE_MENU_MY_ORDERS,
    PAY_ORDER_CALLBACK_PREFIX,
    confirm_agreement_inline_keyboard,
)
from ugc_bot.bot.telegram.handlers.profile import (
    _ADVERTISER_AGREEMENTS_STATE,
    _BLOGGER_AGREEMENTS_STATE,
)
from ugc_bot.bot.telegram.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import OfferDispatch, Order
from ugc_bot.domain.enums import OrderStatus, OrderType

router = Router()

ORDER_STATUS_KEYS = {
    OrderStatus.NEW: "msg_status_new",
    OrderStatus.PENDING_MODERATION: "msg_status_pending_moderation",
    OrderStatus.ACTIVE: "msg_status_active",
    OrderStatus.CLOSED: "msg_status_closed",
}

MY_ORDERS_TEXTS_KEYS = (
    "msg_orders_title",
    "msg_orders_blogger_title",
    "msg_order_status",
    "msg_order_creators",
    "msg_order_matched",
    "msg_order_date_created",
    "msg_order_date_completed",
    "msg_order_link",
    "msg_order_format",
    "msg_order_price",
    "msg_order_barter",
    "msg_order_type_ugc",
    "msg_order_type_placement",
    "msg_status_new",
    "msg_status_pending_moderation",
    "msg_status_active",
    "msg_status_closed",
    "btn_back_arrow",
    "btn_forward_arrow",
    "btn_pay_order",
)


def _format_price(price: float, currency_symbol: str = "₽") -> str:
    """Format price with space as thousands separator and currency symbol."""
    return f"{int(price):,}".replace(",", " ") + f" {currency_symbol}"


def _format_date(dt: Optional[datetime]) -> str:
    """Format date as DD.MM.YYYY or em dash if None."""
    if dt is None:
        return "—"
    return dt.strftime("%d.%m.%Y")


def _format_order_type(
    order: Order, texts: dict[str, str] | None = None
) -> str:
    """Format order type for display."""
    t = texts or {}
    if order.order_type == OrderType.UGC_PLUS_PLACEMENT:
        return t.get("msg_order_type_placement", "UGC + размещение")
    return t.get("msg_order_type_ugc", "UGC-видео для бренда")


def _format_price_and_barter(
    order: Order,
    currency_symbol: str = "₽",
    texts: dict[str, str] | None = None,
) -> list[str]:
    """Return lines for price and/or barter (0-2 lines)."""
    t = texts or {}
    result: list[str] = []
    if order.price > 0:
        price_str = _format_price(order.price, currency_symbol)
        result.append(
            t.get("msg_order_price", "Стоимость 1 UGC: {price}").format(
                price=price_str
            )
        )
    if order.barter_description:
        desc = order.barter_description
        desc_short = desc[:50] + ("…" if len(desc) > 50 else "")
        result.append(
            t.get("msg_order_barter", "Бартер: {desc}").format(desc=desc_short)
        )
    return result


async def _build_currency_map(
    country_repo: CountryRepository | None,
) -> dict[str, str]:
    """Build mapping from currency code to currency symbol."""
    if country_repo is None:
        return {}
    countries = await country_repo.list_enabled()
    result: dict[str, str] = {}
    for c in countries:
        if c.currency_code not in result:
            result[c.currency_code] = c.currency_symbol
    return result


_PAGE_SIZE = 5
_MY_ORDERS_CALLBACK_PREFIX = "my_orders:"
_MY_ORDERS_BLOGGER_CALLBACK_PREFIX = "my_orders_blogger:"


async def _send_my_orders_content(
    incoming,
    state: FSMContext,
    user,
    advertiser,
    blogger,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient,
    locale: str,
    country_repo: CountryRepository | None = None,
) -> None:
    """Send fill profile, agreement, or order lists depending on user state."""
    if advertiser is None and blogger is None:
        msg_fill = await bot_texts_service.get(
            "msg_fill_profile_orders", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_fill,
        )
        return

    agreement_confirmed_at = (
        blogger.agreement_confirmed_at if blogger is not None else None
    ) or (advertiser.agreement_confirmed_at if advertiser is not None else None)
    if agreement_confirmed_at is None:
        agree_keys = [
            "btn_confirm_agreement",
            "msg_confirm_agreement",
            "msg_agreements_intro_default",
            "msg_label_offer",
            "msg_label_privacy",
            "msg_label_consent",
            "msg_confirm_docs_fallback",
        ]
        agree_texts = await bot_texts_service.get_many(agree_keys, locale)
        agreements_text = format_agreements_message(
            config,
            intro=agree_texts.get("msg_confirm_agreement"),
            texts=agree_texts,
            country_code=getattr(user, "country", None),
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=agreements_text,
            keyboard=confirm_agreement_inline_keyboard(
                CALLBACK_PROFILE_AGREE, agree_texts
            ),
            parse_mode="HTML",
        )
        await state.update_data(user_id=user.user_id)
        if blogger is not None:
            await state.set_state(_BLOGGER_AGREEMENTS_STATE)
        else:
            await state.set_state(_ADVERTISER_AGREEMENTS_STATE)
        return

    currency_map = await _build_currency_map(country_repo)
    order_texts = await bot_texts_service.get_many(
        list(MY_ORDERS_TEXTS_KEYS), locale
    )
    if advertiser is not None:
        orders = sorted(
            await order_service.list_by_advertiser(user.user_id),
            key=lambda item: item.created_at,
            reverse=True,
        )
        if orders:
            text, keyboard = await _render_page(
                orders,
                page=1,
                offer_response_service=offer_response_service,
                currency_map=currency_map,
                default_currency_symbol=config.market.currency_symbol,
                texts=order_texts,
            )
            await messenger_client.send_text(
                chat_id=incoming.chat_id, text=text, keyboard=keyboard
            )
        else:
            msg_no_orders = await bot_texts_service.get("msg_no_orders", locale)
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=msg_no_orders,
            )

    if blogger is not None:
        responses = await offer_response_service.list_by_blogger(
            user.user_id, in_offer_only=True
        )
        order_responses = []
        for resp in sorted(
            responses,
            key=lambda r: (r.updated_at or r.created_at, r.created_at),
            reverse=True,
        ):
            order = await order_service.get_order(resp.order_id)
            if order is not None:
                order_responses.append((order, resp))
        if order_responses:
            text, keyboard = _render_blogger_orders_page(
                order_responses,
                page=1,
                currency_map=currency_map,
                default_currency_symbol=config.market.currency_symbol,
                texts=order_texts,
            )
            await messenger_client.send_text(
                chat_id=incoming.chat_id, text=text, keyboard=keyboard
            )
        else:
            msg_no_blogger = await bot_texts_service.get(
                "msg_no_blogger_orders", locale
            )
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=msg_no_blogger,
            )


@router.message(Command("my_orders"))
@router.message(TextEqualsKey("btn_my_orders"))
async def show_my_orders(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    country_repo: CountryRepository | None = None,
) -> None:
    """Show advertiser and blogger orders in two separate messages."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = user_locale
    order_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_my_orders_blocked",
            "msg_my_orders_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=order_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=order_msgs.get("msg_my_orders_blocked", ""),
        pause_msg=order_msgs.get("msg_my_orders_pause", ""),
    )
    if user is None:
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    blogger = await profile_service.get_blogger_profile(user.user_id)
    await _send_my_orders_content(
        incoming,
        state,
        user,
        advertiser,
        blogger,
        order_service,
        offer_response_service,
        config,
        bot_texts_service,
        messenger_client,
        locale,
        country_repo=country_repo,
    )


@router.callback_query(lambda c: c.data == CALLBACK_PROFILE_MENU_MY_ORDERS)
async def show_my_orders_from_profile_callback(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    country_repo: CountryRepository | None = None,
) -> None:
    """Show my orders from profile inline menu."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    locale = user_locale
    order_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_my_orders_blocked",
            "msg_my_orders_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=order_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=order_msgs.get("msg_my_orders_blocked", ""),
        pause_msg=order_msgs.get("msg_my_orders_pause", ""),
    )
    if user is None:
        return
    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    blogger = await profile_service.get_blogger_profile(user.user_id)
    await _send_my_orders_content(
        incoming,
        state,
        user,
        advertiser,
        blogger,
        order_service,
        offer_response_service,
        config,
        bot_texts_service,
        messenger_client,
        locale,
        country_repo=country_repo,
    )


@router.callback_query(
    lambda c: (
        c.data
        and (
            c.data.startswith(_MY_ORDERS_CALLBACK_PREFIX)
            or c.data.startswith(_MY_ORDERS_BLOGGER_CALLBACK_PREFIX)
        )
    )
)
async def paginate_orders(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    order_service: OrderService,
    offer_response_service: OfferResponseService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    country_repo: CountryRepository | None = None,
) -> None:
    """Handle pagination for advertiser and blogger orders."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale
    order_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_my_orders_blocked",
            "msg_my_orders_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=order_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=order_msgs.get("msg_my_orders_blocked", ""),
        pause_msg=order_msgs.get("msg_my_orders_pause", ""),
    )
    if user is None:
        return

    currency_map = await _build_currency_map(country_repo)
    order_texts = await bot_texts_service.get_many(
        list(MY_ORDERS_TEXTS_KEYS), locale
    )
    data = incoming.data or ""
    if data.startswith(_MY_ORDERS_BLOGGER_CALLBACK_PREFIX):
        raw = data.split(_MY_ORDERS_BLOGGER_CALLBACK_PREFIX, 1)[-1]
        blogger = await profile_service.get_blogger_profile(user.user_id)
        if blogger is None:
            msg = await bot_texts_service.get(
                "msg_blogger_profile_empty", locale
            )
            await messenger_client.answer_callback(
                callback_id=incoming.callback_id,
                text=msg,
            )
            return
        try:
            page = int(raw)
        except ValueError:
            page = 1
        responses = await offer_response_service.list_by_blogger(
            user.user_id, in_offer_only=True
        )
        order_responses = []
        for resp in sorted(
            responses,
            key=lambda r: (r.updated_at or r.created_at, r.created_at),
            reverse=True,
        ):
            order = await order_service.get_order(resp.order_id)
            if order is not None:
                order_responses.append((order, resp))
        text, keyboard = _render_blogger_orders_page(
            order_responses,
            page=page,
            currency_map=currency_map,
            default_currency_symbol=config.market.currency_symbol,
            texts=order_texts,
        )
    else:
        raw = data.split(_MY_ORDERS_CALLBACK_PREFIX, 1)[-1]
        advertiser = await profile_service.get_advertiser_profile(user.user_id)
        if advertiser is None:
            msg = await bot_texts_service.get(
                "msg_advertiser_profile_empty", locale
            )
            await messenger_client.answer_callback(
                callback_id=incoming.callback_id,
                text=msg,
            )
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
            orders,
            page=page,
            offer_response_service=offer_response_service,
            currency_map=currency_map,
            default_currency_symbol=config.market.currency_symbol,
            texts=order_texts,
        )

    if incoming.message_id:
        await messenger_client.edit_text(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            text=text,
            keyboard=keyboard,
        )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)


async def _render_page(
    orders,
    page: int,
    offer_response_service: OfferResponseService,
    currency_map: dict[str, str] | None = None,
    default_currency_symbol: str = "₽",
    texts: dict[str, str] | None = None,
) -> tuple[str, Keyboard]:
    """Render paginated orders list."""
    t = texts or {}
    cur_map = currency_map or {}
    total_pages = max(1, ceil(len(orders) / _PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * _PAGE_SIZE
    end = start + _PAGE_SIZE
    slice_orders = orders[start:end]

    title_tpl = t.get(
        "msg_orders_title", "Ваши заказы (страница {page}/{total_pages}):"
    )
    lines = [title_tpl.format(page=page, total_pages=total_pages)]
    buttons_rows: list[list[Button]] = []

    for idx, order in enumerate(slice_orders):
        creation_number = len(orders) - start - idx
        matched_count = await offer_response_service.count_by_order(
            order.order_id
        )
        status_key = ORDER_STATUS_KEYS.get(order.status, "msg_status_new")
        status_label = t.get(status_key, order.status.value)
        status_line = t.get(
            "msg_order_status", "Статус: {status_label}"
        ).format(status_label=status_label)
        creators_line = t.get(
            "msg_order_creators", "Креаторов: {bloggers_needed}"
        ).format(bloggers_needed=order.bloggers_needed)
        matched_line = t.get(
            "msg_order_matched",
            "Подобрано: {matched_count} / {bloggers_needed}",
        ).format(
            matched_count=matched_count, bloggers_needed=order.bloggers_needed
        )
        date_created_line = t.get(
            "msg_order_date_created", "Дата создания: {date}"
        ).format(date=_format_date(order.created_at))
        date_completed_line = t.get(
            "msg_order_date_completed", "Дата завершения: {date}"
        ).format(date=_format_date(order.completed_at))
        link_line = t.get("msg_order_link", "Ссылка на проект: {link}").format(
            link=order.product_link
        )
        sym = cur_map.get(order.currency, default_currency_symbol)
        order_lines = [
            f"№ {creation_number}",
            status_line,
            creators_line,
            matched_line,
            *_format_price_and_barter(order, sym, t),
            date_created_line,
            date_completed_line,
            link_line,
        ]
        lines.append("\n".join(order_lines))
        if order.status == OrderStatus.NEW:
            pay_btn_tpl = t.get(
                "btn_pay_order", "💳 Оплатить №{creation_number}"
            )
            buttons_rows.append(
                [
                    Button(
                        text=pay_btn_tpl.format(
                            creation_number=creation_number
                        ),
                        callback_data=f"{PAY_ORDER_CALLBACK_PREFIX}{order.order_id}",
                    )
                ]
            )

    btn_back = t.get("btn_back_arrow", "⬅️ Назад")
    btn_forward = t.get("btn_forward_arrow", "Вперед ➡️")
    nav_buttons: list[Button] = []
    if page > 1:
        nav_buttons.append(
            Button(
                text=btn_back,
                callback_data=f"{_MY_ORDERS_CALLBACK_PREFIX}{page - 1}",
            )
        )
    if page < total_pages:
        nav_buttons.append(
            Button(
                text=btn_forward,
                callback_data=f"{_MY_ORDERS_CALLBACK_PREFIX}{page + 1}",
            )
        )
    if nav_buttons:
        buttons_rows.append(nav_buttons)

    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=buttons_rows)
    return "\n\n".join(lines), keyboard


def _render_blogger_orders_page(
    order_responses: list[tuple[Order, OfferDispatch]],
    page: int = 1,
    currency_map: dict[str, str] | None = None,
    default_currency_symbol: str = "₽",
    texts: dict[str, str] | None = None,
) -> tuple[str, Keyboard]:
    """Render paginated list of orders the blogger responded to."""
    t = texts or {}
    cur_map = currency_map or {}
    total_pages = max(1, ceil(len(order_responses) / _PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * _PAGE_SIZE
    end = start + _PAGE_SIZE
    slice_pairs = order_responses[start:end]

    orders_sorted_by_created = sorted(
        order_responses, key=lambda pair: pair[0].created_at
    )
    order_id_to_number = {
        order.order_id: idx + 1
        for idx, (order, _) in enumerate(orders_sorted_by_created)
    }

    title_tpl = t.get(
        "msg_orders_blogger_title",
        "Заказы, на которые вы откликнулись (страница {page}/{total_pages}):",
    )
    lines = [title_tpl.format(page=page, total_pages=total_pages)]
    buttons_rows: list[list[Button]] = []

    for order, _response in slice_pairs:
        creation_number = order_id_to_number.get(order.order_id, 0)
        status_key = ORDER_STATUS_KEYS.get(order.status, "msg_status_new")
        status_label = t.get(status_key, order.status.value)
        status_line = t.get(
            "msg_order_status", "Статус: {status_label}"
        ).format(status_label=status_label)
        format_line = t.get("msg_order_format", "Формат: {order_type}").format(
            order_type=_format_order_type(order, t)
        )
        sym = cur_map.get(order.currency, default_currency_symbol)
        order_lines = [
            f"№ {creation_number}",
            status_line,
            format_line,
            *_format_price_and_barter(order, sym, t),
            t.get("msg_order_link", "Ссылка на проект: {link}").format(
                link=order.product_link
            ),
        ]
        lines.append("\n".join(order_lines))

    btn_back = t.get("btn_back_arrow", "⬅️ Назад")
    btn_forward = t.get("btn_forward_arrow", "Вперед ➡️")
    nav_buttons: list[Button] = []
    if page > 1:
        nav_buttons.append(
            Button(
                text=btn_back,
                callback_data=f"{_MY_ORDERS_BLOGGER_CALLBACK_PREFIX}{page - 1}",
            )
        )
    if page < total_pages:
        nav_buttons.append(
            Button(
                text=btn_forward,
                callback_data=f"{_MY_ORDERS_BLOGGER_CALLBACK_PREFIX}{page + 1}",
            )
        )
    if nav_buttons:
        buttons_rows.append(nav_buttons)

    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=buttons_rows)
    return "\n\n".join(lines), keyboard
