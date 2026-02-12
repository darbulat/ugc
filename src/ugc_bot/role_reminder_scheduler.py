"""Scheduler for daily role-choice reminder at configured time (e.g. 10:00)."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot

from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.start import START_TEXT, _role_keyboard
from ugc_bot.bot.handlers.utils import send_with_retry
from ugc_bot.config import load_config
from ugc_bot.infrastructure.db.repositories import SqlAlchemyUserRepository
from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    create_session_factory,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)
_send_retries = 3
_send_retry_delay_seconds = 0.5


def _reminder_cutoff(config) -> datetime:
    """Return today at role_reminder time in configured timezone, as UTC."""

    tz = ZoneInfo(config.role_reminder.role_reminder_timezone)
    now_local = datetime.now(tz)
    today_at_time = now_local.replace(
        hour=config.role_reminder.role_reminder_hour,
        minute=config.role_reminder.role_reminder_minute,
        second=0,
        microsecond=0,
    )
    return today_at_time.astimezone(timezone.utc)


def _seconds_until_next_run(config) -> float:
    """Seconds until next run (same time tomorrow if already passed today)."""

    tz = ZoneInfo(config.role_reminder.role_reminder_timezone)
    now_local = datetime.now(tz)
    today_at_time = now_local.replace(
        hour=config.role_reminder.role_reminder_hour,
        minute=config.role_reminder.role_reminder_minute,
        second=0,
        microsecond=0,
    )
    if now_local < today_at_time:
        next_run = today_at_time
    else:
        next_run = today_at_time + timedelta(days=1)
    return (next_run - now_local).total_seconds()


async def run_once(
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
    reminder_cutoff: datetime,
) -> None:
    """Send one reminder to each user due for a role-choice reminder.

    Updates last_role_reminder_at before sending to avoid race: if the process
    crashes after send but before update, the user would get a duplicate
    reminder next day. By updating first we "reserve" the slot; failed sends
    are logged but the user will not be sent again until the next run.
    """

    users = await user_role_service.list_pending_role_reminders(reminder_cutoff)
    for user in users:
        if user.messenger_type.value != "telegram":  # pragma: no cover
            continue
        try:
            await user_role_service.update_last_role_reminder_at(user.user_id)
            chat_id = int(user.external_id)
            await send_with_retry(
                messenger_client,
                chat_id=str(chat_id),
                text=START_TEXT,
                keyboard=_role_keyboard(),
                retries=_send_retries,
                delay_seconds=_send_retry_delay_seconds,
                logger=logger,
                extra={"user_id": str(user.user_id)},
            )
        except Exception as exc:
            logger.warning(
                "Role reminder send failed",
                extra={
                    "user_id": str(user.user_id),
                    "external_id": user.external_id,
                    "error": str(exc),
                },
            )


async def run_loop(
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
    config,
) -> None:
    """Run role reminder at configured time, then sleep until next run."""

    while True:
        reminder_cutoff = _reminder_cutoff(config)
        await run_once(messenger_client, user_role_service, reminder_cutoff)
        sleep_seconds = _seconds_until_next_run(config)
        logger.info(
            "Role reminder done, sleeping until next run",
            extra={"sleep_seconds": sleep_seconds},
        )
        await asyncio.sleep(sleep_seconds)


def main() -> None:  # pragma: no cover
    """Run role reminder loop (daily at configured time)."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    log_startup_info(
        logger=logger, service_name="Role reminder scheduler", config=config
    )
    if not config.role_reminder.role_reminder_enabled:
        logger.info("Role reminder disabled by config")
        return
    if not config.db.database_url:
        logger.error("DATABASE_URL is required for role reminder")
        return
    session_factory = create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )
    transaction_manager = SessionTransactionManager(session_factory)
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    user_role_service = UserRoleService(
        user_repo=user_repo,
        transaction_manager=transaction_manager,
    )
    bot = Bot(token=config.bot.bot_token)
    messenger_client = TelegramMessengerClient(bot)

    async def _run_with_cleanup() -> None:
        try:
            await run_loop(messenger_client, user_role_service, config)
        finally:
            session = getattr(bot, "session", None)
            if session is not None:
                await session.close()

    asyncio.run(_run_with_cleanup())


if __name__ == "__main__":  # pragma: no cover
    main()
