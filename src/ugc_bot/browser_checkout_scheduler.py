"""Reconcile issued invoices even when new payment creation is paused."""

import asyncio
import logging

logger = logging.getLogger(__name__)


def start_reconciliation(config, container) -> list[asyncio.Task]:
    if not getattr(
        getattr(config, "financial", None), "yookassa_browser_shop_id", ""
    ):
        return []
    checkouts = (
        (container.build_browser_checkout(), "browser-payment-reconciliation"),
        (
            container.build_consultation_checkout(),
            "consultation-payment-reconciliation",
        ),
    )
    return [
        asyncio.create_task(run_loop(checkout), name=name)
        for checkout, name in checkouts
        if checkout is not None
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
