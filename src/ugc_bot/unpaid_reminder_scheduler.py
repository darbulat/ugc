"""Send one Telegram payment reminder for an eligible new order."""

import argparse
import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from aiogram import Bot
from pydantic import AwareDatetime, TypeAdapter
from sqlalchemy import text

from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    NoticeReceiptTransport,
)
from ugc_bot.application.services.customer_workflow_delivery import (
    WorkflowMessage,
)
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.repositories import unpaid_reminders
from ugc_bot.infrastructure.messenger.notice_receipts import (
    TelegramNoticeReceipts,
)

logger = logging.getLogger(__name__)


def _bot_username(config: AppConfig) -> str:
    username = config.bot.bot_username.strip().lstrip("@")
    return username if re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) else ""


async def run_once(
    config: AppConfig,
    container: Container,
    transport: NoticeReceiptTransport,
) -> int:
    start_at = config.order.unpaid_reminders_start_at
    transactions = container.transaction_manager
    username = _bot_username(config)
    now = datetime.now(timezone.utc)
    if (
        not config.order.unpaid_reminders_enabled
        or start_at is None
        or not username
        or transactions is None
        or not unpaid_reminders.in_send_window(now)
    ):
        return 0
    excluded = config.order.unpaid_reminders_excluded_users
    async with transactions.transaction() as session:
        candidates = await unpaid_reminders.list_candidates(
            session, now, start_at, excluded
        )
    count = 0
    for order, user, _ in candidates[:25]:
        async with transactions.transaction() as session:
            address = await unpaid_reminders.reserve(
                session,
                order.order_id,
                user.user_id,
                datetime.now(timezone.utc),
                start_at,
                excluded,
            )
        if not address:
            continue
        message = WorkflowMessage(
            order.order_id,
            "telegram",
            address,
            "chat_id",
            "Здравствуйте! Ваш заказ в UGC ждёт оплаты. Если он ещё актуален, "
            "продолжите по кнопке ниже. Если нужна помощь, откройте заказ "
            "и обратитесь в поддержку.",
            f"https://t.me/{username}?start=pay_{order.order_id}",
            "Продолжить оплату",
        )
        state, reference = await _deliver(transport, message)
        async with transactions.transaction() as session:
            await unpaid_reminders.finish(
                session,
                order.order_id,
                datetime.now(timezone.utc),
                state,
                reference,
            )
        count += 1
    return count


async def _deliver(transport: NoticeReceiptTransport, message: WorkflowMessage):
    try:
        receipt = await transport.send(message)
    except DeliveryFailure as exc:
        if exc.uncertain:
            return "unknown", None
        return (
            "rate_limited"
            if exc.retry_after_seconds is not None
            else "unavailable"
        ), None
    except Exception:
        return "unknown", None
    if receipt.channel != "telegram" or not receipt.reference.strip():
        return "unknown", None
    return "accepted", receipt.reference


async def run_enabled(
    config: AppConfig, container: Container, bot: Bot
) -> None:
    transport = TelegramNoticeReceipts(bot, use_web_app=False)
    while True:
        try:
            await run_once(config, container, transport)
        except Exception as exc:
            logger.warning(
                "Unpaid reminder batch failed: %s", type(exc).__name__
            )
        await asyncio.sleep(60)


async def preview(config: AppConfig, start_at: datetime, at: datetime) -> dict:
    """Evaluate reminder eligibility in a read-only transaction."""
    container = Container(config)
    try:
        transactions = container.transaction_manager
        if transactions is None:
            raise RuntimeError("Database unavailable")
        async with transactions.transaction() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            candidates = await unpaid_reminders.list_candidates(
                session,
                at,
                start_at,
                config.order.unpaid_reminders_excluded_users,
            )
            return {
                "as_of": at.isoformat(),
                "start_at": start_at.isoformat(),
                "send_window": unpaid_reminders.in_send_window(at),
                "bot_configured": bool(_bot_username(config)),
                "count": len(candidates),
                "candidates": [
                    {
                        "customer": brand or user.username,
                        "username": user.telegram or user.username,
                        "order_id": str(order.order_id),
                        "created_at": order.created_at.isoformat(),
                    }
                    for order, user, brand in candidates
                ],
            }
    finally:
        await container.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only unpaid reminder preview"
    )
    parser.add_argument("--start-at", required=True)
    parser.add_argument("--at")
    args = parser.parse_args()
    parse = TypeAdapter(AwareDatetime).validate_python
    at = parse(args.at) if args.at else datetime.now(timezone.utc)
    report = asyncio.run(preview(load_config(), parse(args.start_at), at))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
