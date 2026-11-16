"""Reconcile issued invoices even when new payment creation is paused."""

import asyncio
import logging

logger = logging.getLogger(__name__)


def start_reconciliation(config, container) -> list[asyncio.Task]:
    if not getattr(
        getattr(config, "financial", None), "yookassa_browser_shop_id", ""
    ):
        return []
    checkout = container.build_browser_checkout()
    if checkout is None:
        return []
    return [
        asyncio.create_task(
            run_loop(checkout), name="browser-payment-reconciliation"
        )
    ]


async def run_loop(checkout) -> None:
    while True:
        try:
            processed = await checkout.run_once()
        except Exception as exc:
            logger.error(
                "Browser payment sweep failed (%s)", type(exc).__name__
            )
            processed = False
        await asyncio.sleep(0.1 if processed else 5)
