"""Combined scheduler: runs feedback, role-reminder, and referral-reconciliation
loops in a single process to reduce memory footprint."""

import asyncio
import logging

from aiogram import Bot

from ugc_bot.accompaniment_lead_scheduler import run_enabled as lead_loop
from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.campaign_digest_scheduler import run_enabled as feedback_loop
from ugc_bot.collaboration_scheduler import run_loop as collaboration_loop
from ugc_bot.config import load_config
from ugc_bot.container import Container
from ugc_bot.container.campaign_digest_factory import enabled as digest_enabled
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.notice_delivery_scheduler import run_enabled as notice_loop
from ugc_bot.paid_selection_delivery_scheduler import (
    run_enabled as selection_loop,
)
from ugc_bot.referral_reconciliation_scheduler import (
    run_loop as referral_loop,
)
from ugc_bot.role_reminder_scheduler import run_loop as role_reminder_loop
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


async def _run_all(config, container: Container, bot: Bot) -> None:
    """Launch all enabled scheduler loops concurrently."""
    install_asyncio_exception_handler("combined-scheduler")

    messenger_clients: dict[str, MessengerClient] = {
        "telegram": TelegramMessengerClient(bot),
    }
    tasks: list[asyncio.Task] = []

    if getattr(getattr(config, "financial", None), "core_enabled", False):
        tasks.append(
            asyncio.create_task(
                collaboration_loop(container.build_collaboration_sweep()),
                name="collaboration-deadline-scheduler",
            )
        )
        logger.info("Collaboration deadline scheduler enabled")
        tasks.append(
            asyncio.create_task(
                notice_loop(config, container, bot),
                name="collaboration-notice-delivery",
            )
        )
        logger.info("Collaboration notice delivery enabled")
        tasks.append(
            asyncio.create_task(
                lead_loop(config, container, bot),
                name="accompaniment-lead-delivery",
            )
        )
        logger.info("Accompaniment lead delivery enabled")
        tasks.append(
            asyncio.create_task(
                selection_loop(config, container, bot),
                name="paid-selection-contact-delivery",
            )
        )
        logger.info("Paid selection contact delivery enabled")

    if digest_enabled(config):
        tasks.append(
            asyncio.create_task(
                feedback_loop(config, container, bot),
                name="campaign-summary-scheduler",
            )
        )
        logger.info("Weekly campaign summary scheduler enabled")
    else:
        logger.info(
            "Campaign summaries disabled; legacy rating cascade retired"
        )

    if config.role_reminder.role_reminder_enabled:
        user_role_service = container.build_user_role_service()
        tasks.append(
            asyncio.create_task(
                role_reminder_loop(
                    messenger_clients, user_role_service, config
                ),
                name="role-reminder-scheduler",
            )
        )
        logger.info("Role reminder scheduler enabled")
    else:
        logger.info("Role reminder scheduler disabled by config")

    if config.referral.referral_reconciliation_enabled:
        deps = container.build_referral_reconciliation_deps()
        tasks.append(
            asyncio.create_task(
                referral_loop(
                    income_entry_repo=deps["referral_income_entry_repo"],
                    recorder=deps["recorder"],
                    order_repo=deps["order_repo"],
                    transaction_manager=deps["transaction_manager"],
                    interval_seconds=(
                        config.referral.referral_reconciliation_interval_seconds
                    ),
                ),
                name="referral-reconciliation-scheduler",
            )
        )
        logger.info("Referral reconciliation scheduler enabled")
    else:
        logger.info("Referral reconciliation scheduler disabled by config")

    if not tasks:
        logger.warning("No schedulers enabled, exiting")
        return

    done, pending = await asyncio.wait(
        tasks, return_when=asyncio.FIRST_EXCEPTION
    )
    for task in done:
        if task.exception():
            logger.error(
                "Scheduler task failed: %s",
                task.get_name(),
                exc_info=task.exception(),
            )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


def main() -> None:
    """Entry point for combined scheduler."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("combined-scheduler")
    log_startup_info(
        logger=logger, service_name="Combined scheduler", config=config
    )

    if not config.db.database_url:
        logger.error("DATABASE_URL is required for combined scheduler")
        return

    container = Container(config)
    bot = Bot(token=config.bot.bot_token)

    try:
        asyncio.run(_run_all(config, container, bot))
    finally:
        session = getattr(bot, "session", None)
        if session is not None:
            asyncio.run(session.close())
        asyncio.run(container.dispose())


if __name__ == "__main__":
    main()
