"""Handlers for referral: /referral, /referral_list and payout button."""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from math import ceil
from uuid import UUID, uuid4

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import IntegrityError

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.ports import (
    PayoutRequestRepository,
    TransactionManager,
    UserReferralBindingRepository,
    UserReferralPendingRepository,
    UserRepository,
)
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import PayoutRequest, User
from ugc_bot.domain.enums import PayoutRequestStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

router = Router()
logger = logging.getLogger(__name__)

REFERRAL_PAYOUT_CALLBACK = "referral:payout"
REFERRAL_LIST_CALLBACK_PREFIX = "referral_list:"
PAYOUT_BUTTON_TEXT = "Выплатить"
REFERRAL_LIST_PAGE_SIZE = 10
REFERRAL_LIST_PENDING_LIMIT = 50
USER_NOT_FOUND_MSG = "Пользователь не найден."


def _parse_telegram_arg_from_command(
    text: str | None, command: str
) -> str | None:
    """First arg after /command, normalized (strip, strip @). None if empty."""
    if not text:
        return None
    parts = (text or "").strip().split()
    if len(parts) < 2:
        return None
    arg = parts[1].strip().lstrip("@")
    return arg if arg else None


async def _resolve_referral_target_user(
    current_user: User,
    telegram_arg: str | None,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient,
    chat_id: str,
) -> User | None:
    """Resolve target user for referral commands.

    Returns None only if admin passed @username and that user was not found
    (error message already sent).
    """
    if not current_user.admin:
        return current_user
    if not telegram_arg:
        return current_user
    target = await user_role_service.get_user_by_telegram(telegram_arg)
    if target is None:
        await messenger_client.send_text(
            chat_id=chat_id,
            text=USER_NOT_FOUND_MSG,
        )
        return None
    return target


def _referral_stats_text(
    creators_count: int,
    orders_count: int,
    income_current_month: float,
    income_total: float,
    paid_total: float,
    balance: float,
    currency_symbol: str = "₽",
) -> str:
    """Format referral stats message."""
    return (
        "📊 Реферальная статистика\n\n"
        f"Приведено креаторов: {creators_count}\n"
        f"Выполнено заказов: {orders_count}\n\n"
        f"Доход за текущий месяц: {income_current_month:.2f} "
        f"{currency_symbol}\n"
        f"Накоплено (всего): {income_total:.2f} {currency_symbol}\n"
        f"Выплачено: {paid_total:.2f} {currency_symbol}\n"
        f"Текущий баланс: {balance:.2f} {currency_symbol}"
    )


def _referral_keyboard(
    balance: float,
    has_pending_payout: bool,
    has_request_today: bool,
) -> Keyboard | None:
    """Payout button only when balance > 0, no pending and no request today."""
    if balance <= 0 or has_pending_payout or has_request_today:
        return None
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=PAYOUT_BUTTON_TEXT,
                    callback_data=REFERRAL_PAYOUT_CALLBACK,
                )
            ],
        ],
    )


@router.message(Command("referral"))
async def referral_command(
    message: Message,
    user_role_service: UserRoleService,
    referral_income_service: ReferralIncomeService,
    config: AppConfig,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle /referral — stats; admin may pass @username to view another."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Выберите роль через /role.",
        blocked_msg="Заблокированные не могут использовать команду.",
        pause_msg="Пользователи на паузе не могут использовать команду.",
    )
    if user is None:
        return

    telegram_arg = _parse_telegram_arg_from_command(incoming.text, "referral")
    target = await _resolve_referral_target_user(
        user,
        telegram_arg,
        user_role_service,
        messenger_client,
        incoming.chat_id,
    )
    if target is None:
        return

    stats = await referral_income_service.get_user_referral_stats(
        target.user_id, stats_limit=config.referral.referral_stats_limit
    )
    balance = stats.income_total - stats.paid_total
    text = _referral_stats_text(
        creators_count=stats.creators_count,
        orders_count=stats.orders_count,
        income_current_month=stats.income_current_month,
        income_total=stats.income_total,
        paid_total=stats.paid_total,
        balance=balance,
        currency_symbol=config.market.currency_symbol,
    )
    is_own_view = target.user_id == user.user_id
    bot_username = (config.referral.referral_bot_username or "").strip()
    if is_own_view and bot_username and target.referral_code:
        link = f"https://t.me/{bot_username}?start=ref_{target.referral_code}"
        text = f"Ваша реферальная ссылка:\n{link}\n\n{text}"
    keyboard = (
        _referral_keyboard(
            balance, stats.has_pending_payout, stats.has_request_today
        )
        if is_own_view
        else None
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=keyboard,
    )


@router.callback_query(lambda c: c.data == REFERRAL_PAYOUT_CALLBACK)
async def payout_button_callback(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    referral_income_service: ReferralIncomeService,
    payout_request_repo: PayoutRequestRepository,
    transaction_manager: TransactionManager,
    config: AppConfig,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle 'Выплатить' button — create payout request and notify support."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Не можете запрашивать выплату.",
        pause_msg="Пользователи на паузе не могут запрашивать выплату.",
    )
    if user is None:
        return

    stats = await referral_income_service.get_user_referral_stats(
        user.user_id, stats_limit=config.referral.referral_stats_limit
    )
    if stats.has_request_today:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Вы уже подавали заявку на вывод сегодня.",
            show_alert=True,
        )
        return

    balance = stats.income_total - stats.paid_total
    if stats.has_pending_payout or balance <= 0:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Выплата недоступна: нет баланса или уже есть заявка.",
            show_alert=True,
        )
        return
    request_amount = Decimal(str(round(balance, 2)))

    request = PayoutRequest(
        request_id=uuid4(),
        user_id=user.user_id,
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
        amount=request_amount,
    )

    async def _run(session: object | None) -> None:
        await payout_request_repo.save(request, session=session)

    try:
        await with_optional_tx(transaction_manager, _run)
    except IntegrityError:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Вы уже подавали заявку на вывод сегодня.",
            show_alert=True,
        )
        return

    support_chat_id = config.referral.referral_support_chat_id.strip()
    support_notified = True
    if support_chat_id:
        support_text = (
            f"💰 Запрос на выплату\n\n"
            f"Пользователь: {user.username or '—'}\n"
            f"telegram: @{user.telegram or '—'}\n"
            f"Request ID: {request.request_id}\n"
            f"Сумма: {request_amount:.2f} {config.market.currency_symbol}\n"
            f"Дата: {request.requested_at.strftime('%Y-%m-%d %H:%M')}"
        )
        admin_base = (config.admin.admin_base_url or "").strip()
        if admin_base:
            base = admin_base.rstrip("/")
            edit_url = f"{base}/payout-request-model/edit/{request.request_id}"
            support_text += f"\n\nОткрыть в админке: {edit_url}"
        support_notified = True
        try:
            await messenger_client.send_text(
                chat_id=support_chat_id,
                text=support_text,
            )
        except Exception as e:
            support_notified = False
            logger.error(
                "Failed to send payout request to support channel",
                extra={
                    "user_id": str(user.user_id),
                    "request_id": str(request.request_id),
                    "error": str(e),
                },
            )

    if support_chat_id and not support_notified:
        reply_text = (
            "Заявка создана, но не удалось уведомить поддержку. "
            "Обратитесь в поддержку вручную."
        )
    else:
        reply_text = "Запрос на выплату отправлен в поддержку."

    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text=reply_text,
        show_alert=True,
    )


@router.message(Command("referral_list"))
async def referral_list_command(
    message: Message,
    user_role_service: UserRoleService,
    user_referral_binding_repo: UserReferralBindingRepository,
    user_referral_pending_repo: UserReferralPendingRepository,
    user_repo: UserRepository,
    referral_income_service: ReferralIncomeService,
    transaction_manager: TransactionManager,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle /referral_list — list; admin may pass @username for another."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Выберите роль через /role.",
        blocked_msg="Заблокированные не могут использовать команду.",
        pause_msg="Пользователи на паузе не могут использовать команду.",
    )
    if user is None:
        return

    telegram_arg = _parse_telegram_arg_from_command(
        incoming.text, "referral_list"
    )
    target = await _resolve_referral_target_user(
        user,
        telegram_arg,
        user_role_service,
        messenger_client,
        incoming.chat_id,
    )
    if target is None:
        return

    async with transaction_manager.transaction() as session:
        total_bindings = await user_referral_binding_repo.count_by_referrer(
            target.user_id, session=session
        )
        total_pending = await user_referral_pending_repo.count_by_referrer(
            target.user_id, session=session
        )
    if total_bindings == 0 and total_pending == 0:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="У вас пока нет приведённых пользователей.",
        )
        return

    referrer_user_id_for_callback = (
        target.user_id if target.user_id != user.user_id else None
    )
    text, keyboard = await _render_referral_list_page(
        referrer_user_id=target.user_id,
        page=1,
        user_referral_binding_repo=user_referral_binding_repo,
        user_referral_pending_repo=user_referral_pending_repo,
        user_repo=user_repo,
        referral_income_service=referral_income_service,
        transaction_manager=transaction_manager,
        referrer_user_id_for_callback=referrer_user_id_for_callback,
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=keyboard,
    )


@router.callback_query(
    lambda c: c.data and c.data.startswith(REFERRAL_LIST_CALLBACK_PREFIX)
)
async def referral_list_pagination_callback(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    user_referral_binding_repo: UserReferralBindingRepository,
    user_referral_pending_repo: UserReferralPendingRepository,
    user_repo: UserRepository,
    referral_income_service: ReferralIncomeService,
    transaction_manager: TransactionManager,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle pagination for /referral_list."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден.",
        blocked_msg="Заблокированные не могут просматривать список.",
        pause_msg="Пользователи на паузе не могут просматривать список.",
    )
    if user is None:
        return

    raw = (
        (incoming.data or "")
        .replace(REFERRAL_LIST_CALLBACK_PREFIX, "", 1)
        .strip()
    )
    parts = raw.split(":", 1)
    page_str = (parts[0] or "").strip()
    user_id_str = (parts[1] or "").strip() if len(parts) > 1 else ""
    try:
        page = int(page_str or "1")
    except ValueError:
        page = 1

    referrer_user_id: UUID
    if user_id_str:
        try:
            referrer_user_id = UUID(user_id_str)
        except ValueError:
            referrer_user_id = user.user_id
        else:
            if not user.admin:
                await messenger_client.answer_callback(
                    callback_id=incoming.callback_id,
                    text="Доступ запрещён.",
                    show_alert=True,
                )
                return
    else:
        referrer_user_id = user.user_id

    referrer_user_id_for_callback = (
        referrer_user_id if referrer_user_id != user.user_id else None
    )
    text, keyboard = await _render_referral_list_page(
        referrer_user_id=referrer_user_id,
        page=page,
        user_referral_binding_repo=user_referral_binding_repo,
        user_referral_pending_repo=user_referral_pending_repo,
        user_repo=user_repo,
        referral_income_service=referral_income_service,
        transaction_manager=transaction_manager,
        referrer_user_id_for_callback=referrer_user_id_for_callback,
    )
    if incoming.message_id:
        await messenger_client.edit_text(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            text=text,
            keyboard=keyboard,
        )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)


def _user_display_name(telegram: str | None, username: str | None) -> str:
    """Format user for list display: @telegram or username or placeholder."""
    if telegram:
        return f"@{telegram}"
    return username or "—"


async def _build_referral_block1(
    *,
    referrer_user_id: UUID,
    page: int,
    user_referral_binding_repo: UserReferralBindingRepository,
    user_repo: UserRepository,
    referral_income_service: ReferralIncomeService,
    session: object,
) -> tuple[list[str], int, int, int]:
    """Build block 1 (bindings). Returns (lines, total_pages, total, page)."""
    total_bindings = await user_referral_binding_repo.count_by_referrer(
        referrer_user_id, session=session
    )
    if total_bindings == 0:
        return (["Ваши рефералы: пока никого."], 1, 0, 1)
    total_pages = max(1, ceil(total_bindings / REFERRAL_LIST_PAGE_SIZE))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * REFERRAL_LIST_PAGE_SIZE
    bindings = list(
        await user_referral_binding_repo.list_by_referrer(
            referrer_user_id,
            offset=offset,
            limit=REFERRAL_LIST_PAGE_SIZE,
            session=session,
        )
    )
    referred_ids = [b.referred_user_id for b in bindings]
    users_map = await user_repo.get_by_ids(referred_ids, session=session)
    completed_map = (
        await referral_income_service.count_completed_orders_by_user_ids(
            referred_ids, session=session
        )
    )
    names = []
    for b in bindings:
        u = users_map.get(b.referred_user_id)
        names.append(
            _user_display_name(
                u.telegram if u else None,
                u.username if u else None,
            )
        )
    lines = [f"Ваши рефералы (страница {page}/{total_pages}):"]
    for idx, (binding, name) in enumerate(
        zip(bindings, names, strict=True), start=offset + 1
    ):
        completed = completed_map.get(binding.referred_user_id, 0)
        lines.append(f"{idx}. {name} — выполнено заказов: {completed}")
    return lines, total_pages, total_bindings, page


async def _build_pending_block2(
    *,
    referrer_user_id: UUID,
    user_referral_pending_repo: UserReferralPendingRepository,
    user_repo: UserRepository,
    session: object,
) -> list[str]:
    """Build block 2 lines (pending users without creator profile)."""
    lines = ["Не заполнили профиль креатора (напоминайте заполнить):"]
    pending_count = await user_referral_pending_repo.count_by_referrer(
        referrer_user_id, session=session
    )
    if pending_count == 0:
        lines.append("Нет рефералов без профиля.")
        return lines
    pending_list = list(
        await user_referral_pending_repo.list_by_referrer(
            referrer_user_id,
            offset=0,
            limit=REFERRAL_LIST_PENDING_LIMIT,
            session=session,
        )
    )
    if pending_list:
        pending_user_ids = [p.user_id for p in pending_list]
        users_map = await user_repo.get_by_ids(
            pending_user_ids, session=session
        )
        for pending in pending_list:
            u = users_map.get(pending.user_id)
            name = _user_display_name(
                u.telegram if u else None,
                u.username if u else None,
            )
            lines.append(f"• {name}")
    return lines


def _referral_list_pagination_keyboard(
    page: int,
    total_pages: int,
    total_bindings: int,
    referrer_user_id_for_callback: UUID | None = None,
) -> Keyboard:
    """Pagination keyboard for referral list when bindings exist."""
    if total_bindings == 0:
        return Keyboard(kind=KeyboardKind.INLINE, rows=[])
    suffix = (
        f":{referrer_user_id_for_callback}"
        if referrer_user_id_for_callback
        else ""
    )
    nav_buttons: list[Button] = []
    prefix = REFERRAL_LIST_CALLBACK_PREFIX
    if page > 1:
        nav_buttons.append(
            Button(
                text="Назад",
                callback_data=f"{prefix}{page - 1}{suffix}",
            )
        )
    if page < total_pages:
        nav_buttons.append(
            Button(
                text="Вперёд",
                callback_data=f"{prefix}{page + 1}{suffix}",
            )
        )
    rows = [nav_buttons] if nav_buttons else []
    return Keyboard(kind=KeyboardKind.INLINE, rows=rows)


async def _render_referral_list_page(
    *,
    referrer_user_id: UUID,
    page: int,
    user_referral_binding_repo: UserReferralBindingRepository,
    user_referral_pending_repo: UserReferralPendingRepository,
    user_repo: UserRepository,
    referral_income_service: ReferralIncomeService,
    transaction_manager: TransactionManager,
    referrer_user_id_for_callback: UUID | None = None,
) -> tuple[str, Keyboard]:
    """Build referral list: block 1 (bindings), block 2 (pending)."""
    async with transaction_manager.transaction() as session:
        (
            block1_lines,
            total_pages,
            total_bindings,
            current_page,
        ) = await _build_referral_block1(
            referrer_user_id=referrer_user_id,
            page=page,
            user_referral_binding_repo=user_referral_binding_repo,
            user_repo=user_repo,
            referral_income_service=referral_income_service,
            session=session,
        )
        block2_lines = await _build_pending_block2(
            referrer_user_id=referrer_user_id,
            user_referral_pending_repo=user_referral_pending_repo,
            user_repo=user_repo,
            session=session,
        )
    text = "\n".join(block1_lines) + "\n\n" + "\n".join(block2_lines)
    keyboard = _referral_list_pagination_keyboard(
        current_page,
        total_pages,
        total_bindings,
        referrer_user_id_for_callback=referrer_user_id_for_callback,
    )
    return text, keyboard
