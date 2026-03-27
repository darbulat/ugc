"""Scheduler for daily role-choice reminder at configured time (e.g. 10:00)."""

import asyncio
import functools
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot

from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.keyboards import role_inline_keyboard
from ugc_bot.bot.telegram.handlers.utils import send_with_retry
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.config import load_config
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import UserStatus
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


async def _mark_bot_blocked(
    user: User, user_role_service: UserRoleService
) -> None:
    """Mark user as BOT_BLOCKED; log and swallow errors."""
    try:
        await user_role_service.update_status(
            user.user_id, UserStatus.BOT_BLOCKED
        )
    except Exception:
        logger.exception(
            "Failed to mark user as bot_blocked",
            extra={"user_id": str(user.user_id)},
        )


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


def _reminder_text_and_keyboard(config, user_locale: str | None = None):
    """Start message and role keyboard for reminder."""
    default_locale = getattr(config.market, "default_locale", "ru") or "ru"
    locale = user_locale or default_locale
    locale_texts = DEFAULT_TEXTS.get(locale) or DEFAULT_TEXTS["ru"]
    start_text = locale_texts.get(
        "msg_start", locale_texts.get("start_message", "")
    )
    keys = ["btn_creator", "btn_advertiser", "btn_support"]
    texts = {k: locale_texts.get(k, "") for k in keys}
    return start_text, role_inline_keyboard(texts)


async def run_once(
    messenger_clients: dict[str, MessengerClient],
    user_role_service: UserRoleService,
    reminder_cutoff: datetime,
    config,
) -> None:
    """Send one reminder to each user due for a role-choice reminder.

    Updates last_role_reminder_at before sending to avoid race: if the process
    crashes after send but before update, the user would get a duplicate
    reminder next day. By updating first we "reserve" the slot; failed sends
    are logged but the user will not be sent again until the next run.
    """

    users = await user_role_service.list_pending_role_reminders(reminder_cutoff)
    for user in users:
        try:
            await user_role_service.update_last_role_reminder_at(user.user_id)
            user_locale = user.language or None
            start_text, keyboard = _reminder_text_and_keyboard(
                config, user_locale=user_locale
            )
            targets: list[tuple[str, MessengerClient]] = []
            if user.telegram_id and "telegram" in messenger_clients:
                targets.append(
                    (user.telegram_id, messenger_clients["telegram"])
                )
            if user.max_chat_id and "max" in messenger_clients:
                targets.append((user.max_chat_id, messenger_clients["max"]))
            for chat_id, client in targets:
                await send_with_retry(
                    client,
                    chat_id=chat_id,
                    text=start_text,
                    keyboard=keyboard,
                    retries=_send_retries,
                    delay_seconds=_send_retry_delay_seconds,
                    logger=logger,
                    extra={"user_id": str(user.user_id)},
                    on_bot_blocked=functools.partial(
                        _mark_bot_blocked, user, user_role_service
                    ),
                )
        except Exception as exc:
            logger.warning(
                "Role reminder send failed",
                extra={
                    "user_id": str(user.user_id),
                    "telegram_id": user.telegram_id,
                    "max_id": user.max_id,
                    "error": str(exc),
                },
            )


async def run_loop(
    messenger_clients: dict[str, MessengerClient],
    user_role_service: UserRoleService,
    config,
) -> None:
    """Run role reminder at configured time, then sleep until next run."""

    while True:
        reminder_cutoff = _reminder_cutoff(config)
        await run_once(
            messenger_clients, user_role_service, reminder_cutoff, config
        )
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
    messenger_clients: dict[str, MessengerClient] = {
        "telegram": TelegramMessengerClient(bot),
    }

    async def _run_with_cleanup() -> None:
        try:
            await run_loop(messenger_clients, user_role_service, config)
        finally:
            session = getattr(bot, "session", None)
            if session is not None:
                await session.close()

    asyncio.run(_run_with_cleanup())


if __name__ == "__main__":  # pragma: no cover
    main()
