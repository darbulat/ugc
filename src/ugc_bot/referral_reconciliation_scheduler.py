"""Scheduler that reconciles missing referral income entries."""

import asyncio
import logging

from ugc_bot.application.ports import ReferralIncomeEntryRepository
from ugc_bot.application.services.referral_income_recorder import (
    ReferralIncomeRecorder,
)
from ugc_bot.config import load_config
from ugc_bot.container import Container
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.infrastructure.db.session import with_optional_tx
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


async def run_once(
    income_entry_repo: ReferralIncomeEntryRepository,
    recorder: ReferralIncomeRecorder,
    order_repo,
    transaction_manager,
    batch_limit: int = 100,
) -> int:
    """Find and record missing referral income entries. Return count."""
    recorded = 0

    async def _run(session):
        nonlocal recorded
        missing_creators = await income_entry_repo.find_missing_creator_income(
            limit=batch_limit, session=session
        )
        for m in missing_creators:
            order = await order_repo.get_by_id(m.order_id, session=session)
            if order is None:
                continue
            try:
                await recorder.record_creator_referral_income(
                    order=order,
                    creator_id=m.referred_user_id,
                    advertiser_country_code=m.advertiser_country_code,
                    session=session,
                )
                recorded += 1
            except Exception:
                logger.error(
                    "Failed to reconcile creator income for order %s",
                    m.order_id,
                    exc_info=True,
                )

        missing_advertisers = (
            await income_entry_repo.find_missing_advertiser_income(
                limit=batch_limit, session=session
            )
        )
        for m in missing_advertisers:
            order = await order_repo.get_by_id(m.order_id, session=session)
            if order is None:
                continue
            try:
                await recorder.record_advertiser_referral_income(
                    order=order,
                    advertiser_id=m.referred_user_id,
                    advertiser_country_code=m.advertiser_country_code,
                    session=session,
                )
                recorded += 1
            except Exception:
                logger.error(
                    "Failed to reconcile advertiser income for order %s",
                    m.order_id,
                    exc_info=True,
                )

    await with_optional_tx(transaction_manager, _run)
    if recorded:
        logger.info("Reconciled %d missing referral income entries", recorded)
    return recorded


async def run_loop(
    income_entry_repo: ReferralIncomeEntryRepository,
    recorder: ReferralIncomeRecorder,
    order_repo,
    transaction_manager,
    interval_seconds: int,
    max_iterations: int | None = None,
) -> int:
    """Run periodic reconciliation. Return total iterations for testing."""
    install_asyncio_exception_handler("referral-reconciliation")
    iterations = 0
    logger.info("Referral reconciliation scheduler started")
    try:
        while True:
            iterations += 1
            await run_once(
                income_entry_repo, recorder, order_repo, transaction_manager
            )
            if max_iterations is not None and iterations >= max_iterations:
                return iterations
            await asyncio.sleep(interval_seconds)
    finally:
        logger.info(
            "Referral reconciliation scheduler stopped",
            extra={"total_iterations": iterations},
        )


def main() -> None:
    """Entry point for referral reconciliation scheduler."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("referral-reconciliation")
    log_startup_info(
        logger=logger,
        service_name="Referral reconciliation scheduler",
        config=config,
    )

    if not config.referral.referral_reconciliation_enabled:
        logger.info("Referral reconciliation scheduler disabled by config")
        return

    if not config.db.database_url:
        logger.error("DATABASE_URL is required for reconciliation scheduler")
        return

    container = Container(config)
    deps = container.build_referral_reconciliation_deps()

    asyncio.run(
        run_loop(
            income_entry_repo=deps["referral_income_entry_repo"],
            recorder=deps["recorder"],
            order_repo=deps["order_repo"],
            transaction_manager=deps["transaction_manager"],
            interval_seconds=(
                config.referral.referral_reconciliation_interval_seconds
            ),
        )
    )


if __name__ == "__main__":
    main()
