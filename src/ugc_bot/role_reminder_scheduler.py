"""Scheduler for daily role-choice reminder at configured time (e.g. 10:00)."""

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.start import START_TEXT, _role_keyboard
from ugc_bot.bot.handlers.utils import send_with_retry
from ugc_bot.config import load_config
from ugc_bot.infrastructure.db.repositories import SqlAlchemyUserRepository
from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    create_session_factory,
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


async def run_once(
    bot: Bot,
    user_role_service: UserRoleService,
    reminder_cutoff: datetime,
) -> None:
    """Send one reminder to each user due for a role-choice reminder."""

    users = await user_role_service.list_pending_role_reminders(reminder_cutoff)
    for user in users:
        if user.messenger_type.value != "telegram":  # pragma: no cover
            continue
        try:
            chat_id = int(user.external_id)
            await send_with_retry(
                bot,
                chat_id=chat_id,
                text=START_TEXT,
                reply_markup=_role_keyboard(),
                retries=_send_retries,
                delay_seconds=_send_retry_delay_seconds,
                logger=logger,
                extra={"user_id": str(user.user_id)},
            )
            await user_role_service.update_last_role_reminder_at(user.user_id)
        except Exception as exc:
            logger.warning(
                "Role reminder send failed",
                extra={
                    "user_id": str(user.user_id),
                    "external_id": user.external_id,
                    "error": str(exc),
                },
            )


def main() -> None:  # pragma: no cover
    """Run role reminder once (invoke from cron at 10:00)."""
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
    reminder_cutoff = _reminder_cutoff(config)
    bot = Bot(token=config.bot.bot_token)
    asyncio.run(run_once(bot, user_role_service, reminder_cutoff))


if __name__ == "__main__":  # pragma: no cover
    main()
