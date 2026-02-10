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
from ugc_bot.domain.entities import PayoutRequest
from ugc_bot.domain.enums import PayoutRequestStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

router = Router()
logger = logging.getLogger(__name__)

REFERRAL_PAYOUT_CALLBACK = "referral:payout"
REFERRAL_LIST_CALLBACK_PREFIX = "referral_list:"
PAYOUT_BUTTON_TEXT = "Выплатить"
REFERRAL_LIST_PAGE_SIZE = 10


def _referral_stats_text(
    creators_count: int,
    orders_count: int,
    income_current_month: float,
    income_total: float,
    paid_total: float,
    balance: float,
) -> str:
    """Format referral stats message."""
    return (
        "📊 Реферальная статистика\n\n"
        f"Приведено креаторов: {creators_count}\n"
        f"Выполнено заказов: {orders_count}\n\n"
        f"Доход за текущий месяц: {income_current_month:.2f} ₽\n"
        f"Накоплено (всего): {income_total:.2f} ₽\n"
        f"Выплачено: {paid_total:.2f} ₽\n"
        f"Текущий баланс: {balance:.2f} ₽"
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
    """Handle /referral — show current user referral stats (all users)."""
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

    stats = await referral_income_service.get_user_referral_stats(
        user.user_id, stats_limit=config.referral.referral_stats_limit
    )
    balance = stats.income_total - stats.paid_total
    text = _referral_stats_text(
        creators_count=stats.creators_count,
        orders_count=stats.orders_count,
        income_current_month=stats.income_current_month,
        income_total=stats.income_total,
        paid_total=stats.paid_total,
        balance=balance,
    )
    bot_username = (config.referral.referral_bot_username or "").strip()
    if bot_username and user.referral_code:
        link = f"https://t.me/{bot_username}?start=ref_{user.referral_code}"
        text = f"Ваша реферальная ссылка:\n{link}\n\n{text}"
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=_referral_keyboard(
            balance, stats.has_pending_payout, stats.has_request_today
        ),
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
            f"telegram: @{user.telegram}\n"
            f"Request ID: {request.request_id}\n"
            f"Сумма: {request_amount:.2f} ₽\n"
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
    user_repo: UserRepository,
    referral_income_service: ReferralIncomeService,
    transaction_manager: TransactionManager,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle /referral_list — list users referred by current user (page 1)."""
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

    async with transaction_manager.transaction() as session:
        total = await user_referral_binding_repo.count_by_referrer(
            user.user_id, session=session
        )
    if total == 0:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="У вас пока нет приведённых пользователей.",
        )
        return

    text, keyboard = await _render_referral_list_page(
        referrer_user_id=user.user_id,
        page=1,
        user_referral_binding_repo=user_referral_binding_repo,
        user_repo=user_repo,
        referral_income_service=referral_income_service,
        transaction_manager=transaction_manager,
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

    raw = (incoming.data or "").replace(REFERRAL_LIST_CALLBACK_PREFIX, "")
    try:
        page = int(raw)
    except ValueError:
        page = 1

    text, keyboard = await _render_referral_list_page(
        referrer_user_id=user.user_id,
        page=page,
        user_referral_binding_repo=user_referral_binding_repo,
        user_repo=user_repo,
        referral_income_service=referral_income_service,
        transaction_manager=transaction_manager,
    )
    if incoming.message_id:
        await messenger_client.edit_text(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            text=text,
            keyboard=keyboard,
        )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)


async def _render_referral_list_page(
    *,
    referrer_user_id: UUID,
    page: int,
    user_referral_binding_repo: UserReferralBindingRepository,
    user_repo: UserRepository,
    referral_income_service: ReferralIncomeService,
    transaction_manager: TransactionManager,
) -> tuple[str, Keyboard]:
    """Build one page of referral list text and pagination keyboard."""
    async with transaction_manager.transaction() as session:
        total = await user_referral_binding_repo.count_by_referrer(
            referrer_user_id, session=session
        )
        total_pages = max(1, ceil(total / REFERRAL_LIST_PAGE_SIZE))
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
        names: list[str] = []
        for binding in bindings:
            referred = await user_repo.get_by_id(
                binding.referred_user_id, session=session
            )
            if referred:
                name = (
                    f"@{referred.telegram}"
                    if referred.telegram
                    else (referred.username or "—")
                )
            else:
                name = "—"
            names.append(name)

        lines = [f"Ваши рефералы (страница {page}/{total_pages}):"]
        for idx, (binding, name) in enumerate(
            zip(bindings, names, strict=True), start=offset + 1
        ):
            completed = (
                await referral_income_service.count_completed_orders_for_user(
                    binding.referred_user_id, session=session
                )
            )
            lines.append(f"{idx}. {name} — выполнено заказов: {completed}")

    buttons_rows: list[list[Button]] = []
    nav_buttons: list[Button] = []
    if page > 1:
        nav_buttons.append(
            Button(
                text="Назад",
                callback_data=f"{REFERRAL_LIST_CALLBACK_PREFIX}{page - 1}",
            )
        )
    if page < total_pages:
        nav_buttons.append(
            Button(
                text="Вперёд",
                callback_data=f"{REFERRAL_LIST_CALLBACK_PREFIX}{page + 1}",
            )
        )
    if nav_buttons:
        buttons_rows.append(nav_buttons)

    keyboard = (
        Keyboard(kind=KeyboardKind.INLINE, rows=buttons_rows)
        if buttons_rows
        else Keyboard(kind=KeyboardKind.INLINE, rows=[])
    )
    return "\n".join(lines), keyboard
