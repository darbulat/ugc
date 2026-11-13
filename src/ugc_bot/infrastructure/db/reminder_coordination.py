"""Shared daily exclusion for automatic customer reminders."""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ORDER_REMINDER = "unpaid_order_reminder"
CLIENT_REMINDER = "unpaid_reminder_recipient"
MOSCOW = ZoneInfo("Europe/Moscow")


def moscow_day_start(at: datetime) -> datetime:
    return at.astimezone(MOSCOW).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


async def lock_customer_reminders(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"customer-reminder:{user_id}"},
    )
