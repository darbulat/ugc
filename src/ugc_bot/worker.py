"""Unified worker: runs all background schedulers in one process."""

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import Bot

from ugc_bot import (
    feedback_scheduler,
    instagram_stats_collector_scheduler,
    instagram_stats_scheduler,
    referral_reconciliation_scheduler,
    role_reminder_scheduler,
)
from ugc_bot.application.messenger.dto import Invoice, Keyboard
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


class _NoCloseMessengerClient:
    """Wraps a messenger client; makes close() a no-op.

    Used to prevent feedback_scheduler.run_loop's finally block from closing
    the shared Bot session while other schedulers are still running.
    The real session is closed by worker.main() after all tasks complete.
    """

    def __init__(self, delegate: Any) -> None:
        self._d = delegate

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
        disable_preview: bool | None = None,
    ) -> None:
        await self._d.send_text(
            chat_id=chat_id,
            text=text,
            keyboard=keyboard,
            parse_mode=parse_mode,
            disable_preview=disable_preview,
        )

    async def send_photo(
        self,
        *,
        chat_id: str,
        file_id: str,
        caption: str | None = None,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        await self._d.send_photo(
            chat_id=chat_id,
            file_id=file_id,
            caption=caption,
            keyboard=keyboard,
            parse_mode=parse_mode,
        )

    async def edit_text(
        self,
        *,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        await self._d.edit_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            keyboard=keyboard,
            parse_mode=parse_mode,
        )

    async def edit_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        await self._d.edit_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            keyboard=keyboard,
        )

    async def answer_callback(
        self,
        *,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        await self._d.answer_callback(
            callback_id=callback_id,
            text=text,
            show_alert=show_alert,
        )

    async def send_invoice(self, *, chat_id: str, invoice: Invoice) -> None:
        await self._d.send_invoice(chat_id=chat_id, invoice=invoice)

    async def close(self) -> None:
        """No-op: the shared Bot session is closed by worker.main()."""


async def _run_with_restart(
    name: str,
    coro_factory: Callable[[], Awaitable[Any]],
    restart_delay: float = 5.0,
) -> None:
    """Run coro_factory() in an infinite loop; restart after exceptions.

    Only BaseException (e.g. CancelledError on shutdown) escapes this loop.
    That correctly propagates cancellation through asyncio.gather.
    """
    while True:
        try:
            await coro_factory()
        except Exception:
            logger.exception(
                "Scheduler %s crashed, restarting in %.0fs", name, restart_delay
            )
            await asyncio.sleep(restart_delay)


async def main_async(  # noqa: C901
    config: AppConfig,
    container: Container,
    messenger_client: Any,
) -> None:
    """Initialize all enabled schedulers and run them concurrently."""
    install_asyncio_exception_handler("worker")

    tasks = []

    if config.feedback.feedback_enabled:
        deps = container.build_feedback_scheduler_deps()
        bot_texts_service = container.build_bot_texts_service()
        default_locale = (
            (config.market.default_locale or "ru") if config.market else "ru"
        )
        no_close = _NoCloseMessengerClient(messenger_client)

        # Use default-argument capture to freeze values at task-creation time,
        # preventing the classic Python closure-over-mutable-variable bug.
        def _feedback_factory(  # noqa: E306  # pragma: no cover
            d: Any = deps,
            t: Any = bot_texts_service,
            c: Any = no_close,
            loc: str = default_locale,
        ) -> Awaitable[Any]:
            return feedback_scheduler.run_loop(
                c,
                d["interaction_repo"],
                d["interaction_service"],
                d["user_role_service"],
                d["profile_service"],
                d["order_repo"],
                config.feedback,
                interval_seconds=config.feedback.feedback_poll_interval_seconds,  # noqa: E501
                transaction_manager=d["transaction_manager"],
                default_locale=loc,
                bot_texts_service=t,
            )

        tasks.append(_run_with_restart("feedback", _feedback_factory))
    else:
        logger.info("Feedback scheduler disabled by config")

    if config.role_reminder.role_reminder_enabled:
        deps = container.build_role_reminder_scheduler_deps()

        def _role_reminder_factory(d: Any = deps) -> Awaitable[Any]:  # noqa: E306  # pragma: no cover
            return role_reminder_scheduler.run_loop(
                messenger_client,
                d["user_role_service"],
                config,
            )

        tasks.append(_run_with_restart("role_reminder", _role_reminder_factory))
    else:
        logger.info("Role reminder scheduler disabled by config")

    if config.referral.referral_reconciliation_enabled:
        deps = container.build_referral_reconciliation_deps()

        def _referral_factory(d: Any = deps) -> Awaitable[Any]:  # noqa: E306  # pragma: no cover
            return referral_reconciliation_scheduler.run_loop(
                income_entry_repo=d["referral_income_entry_repo"],
                recorder=d["recorder"],
                order_repo=d["order_repo"],
                transaction_manager=d["transaction_manager"],
                interval_seconds=config.referral.referral_reconciliation_interval_seconds,  # noqa: E501
            )

        tasks.append(
            _run_with_restart("referral_reconciliation", _referral_factory)
        )
    else:
        logger.info("Referral reconciliation scheduler disabled by config")

    if config.instagram.instagram_stats_update_enabled:
        deps = container.build_instagram_stats_scheduler_deps()

        def _instagram_stats_factory(d: Any = deps) -> Awaitable[Any]:  # noqa: E306  # pragma: no cover
            return instagram_stats_scheduler.run_loop(
                d["instagram_stats_update_service"],
                interval_seconds=d["interval_seconds"],
            )

        tasks.append(
            _run_with_restart("instagram_stats", _instagram_stats_factory)
        )
    else:
        logger.info("Instagram stats scheduler disabled by config")

    if config.instagram.instagram_stats_collector_enabled:
        deps = container.build_instagram_stats_collector_scheduler_deps()

        def _instagram_collector_factory(  # noqa: E306  # pragma: no cover
            d: Any = deps,
        ) -> Awaitable[Any]:
            return instagram_stats_collector_scheduler.run_loop(
                d["instagram_stats_collector_service"],
                interval_seconds=d["interval_seconds"],
            )

        tasks.append(
            _run_with_restart(
                "instagram_stats_collector", _instagram_collector_factory
            )
        )
    else:
        logger.info("Instagram stats collector scheduler disabled by config")

    if not tasks:
        logger.warning("All schedulers are disabled; worker is idle")
        await asyncio.sleep(float("inf"))
        return

    await asyncio.gather(*tasks)


def main() -> None:  # pragma: no cover
    """Entry point for unified worker process."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("worker")
    log_startup_info(logger=logger, service_name="Worker", config=config)

    container = Container(config)
    bot = Bot(token=config.bot.bot_token)
    messenger_client = TelegramMessengerClient(bot)

    async def _run() -> None:
        try:
            await main_async(config, container, messenger_client)
        finally:
            await container.dispose()
            session = getattr(bot, "session", None)
            if session is not None:
                await session.close()

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    main()
