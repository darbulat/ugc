"""Handlers for referral managers: /referal command and payout button."""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
)
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
PAYOUT_BUTTON_TEXT = "Выплатить"


def _referral_stats_text(
    creators_count: int,
    orders_count: int,
    income_current_month: float,
    income_total: float,
) -> str:
    """Format referral stats message."""
    return (
        "📊 Реферальная статистика\n\n"
        f"Приведено креаторов: {creators_count}\n"
        f"Выполнено заказов: {orders_count}\n\n"
        f"Доход за текущий месяц: {income_current_month:.2f} ₽\n"
        f"Общий баланс: {income_total:.2f} ₽"
    )


def _referral_keyboard() -> Keyboard:
    """Build keyboard with payout button."""
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


@router.message(Command("referal"))
async def referal_command(
    message: Message,
    user_role_service,
    manager_repo,
    referral_income_service: ReferralIncomeService,
    config: AppConfig,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle /referal command — show manager stats (managers only)."""
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

    manager = await manager_repo.get_by_user_id(user.user_id)
    if manager is None:
        return

    stats = await referral_income_service.get_manager_stats(manager.manager_id)
    text = _referral_stats_text(
        creators_count=stats.creators_count,
        orders_count=stats.orders_count,
        income_current_month=stats.income_current_month,
        income_total=stats.income_total,
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=_referral_keyboard(),
    )


@router.callback_query(lambda c: c.data == REFERRAL_PAYOUT_CALLBACK)
async def payout_button_callback(
    callback: CallbackQuery,
    user_role_service,
    manager_repo,
    payout_request_repo,
    transaction_manager,
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

    manager = await manager_repo.get_by_user_id(user.user_id)
    if manager is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Менеджер не найден.",
            show_alert=True,
        )
        return

    request = PayoutRequest(
        request_id=uuid4(),
        manager_id=manager.manager_id,
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
    )

    async def _run(session: object | None) -> None:
        await payout_request_repo.save(request, session=session)

    await with_optional_tx(transaction_manager, _run)

    support_chat_id = config.referral.referral_support_chat_id.strip()
    if support_chat_id:
        support_text = (
            f"💰 Запрос на выплату\n\n"
            f"Менеджер: {manager.name or user.username or '—'}\n"
            f"User ID: {user.external_id}\n"
            f"Request ID: {request.request_id}\n"
            f"Дата: {request.requested_at.strftime('%Y-%m-%d %H:%M')}"
        )
        try:
            await messenger_client.send_text(
                chat_id=support_chat_id,
                text=support_text,
            )
        except Exception as e:
            logger.warning(
                "Failed to send payout request to support channel",
                extra={
                    "manager_id": str(manager.manager_id),
                    "request_id": str(request.request_id),
                    "error": str(e),
                },
            )

    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text="Запрос на выплату отправлен в поддержку.",
        show_alert=True,
    )
