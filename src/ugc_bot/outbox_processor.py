"""Background processor for outbox events."""

import asyncio
import contextlib
import logging
from datetime import datetime, timezone
from typing import Optional

from ugc_bot.application.ports import OrderActivationPublisher
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.config import OutboxConfig, load_config
from ugc_bot.container import Container
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


class OutboxProcessor:
    """Background processor for outbox events."""

    def __init__(
        self,
        outbox_publisher: OutboxPublisher,
        kafka_publisher: OrderActivationPublisher,
        poll_interval: float = 5.0,
        max_retries: int = 3,
        outbox_config: Optional[OutboxConfig] = None,
    ):
        self.outbox_publisher = outbox_publisher
        self.kafka_publisher = kafka_publisher
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self._outbox_config = outbox_config
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._iteration_count = 0

    async def start(self) -> None:
        """Start the background processor."""

        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("Outbox processor started")

    async def stop(self) -> None:
        """Stop the background processor."""

        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Outbox processor stopped")

    async def _process_loop(self) -> None:
        """Main processing loop."""

        while self._running:
            try:
                await self._process_batch()
                self._iteration_count += 1
                await self._maybe_run_cleanup()
            except Exception as e:
                logger.exception("Error in outbox processing loop: %s", e)

            await asyncio.sleep(self.poll_interval)

    async def _maybe_run_cleanup(self) -> None:
        """Run cleanup every N iterations if config is available."""

        if (
            self._outbox_config is None
            or self._outbox_config.outbox_retention_days <= 0
        ):
            return

        interval = self._outbox_config.outbox_cleanup_interval_iterations
        if interval <= 0 or self._iteration_count % interval != 0:
            return

        try:
            deleted = await self.outbox_publisher.cleanup_processed_events(
                retention_days=self._outbox_config.outbox_retention_days,
                batch_size=self._outbox_config.outbox_cleanup_batch_size,
            )
            if deleted > 0:
                logger.info(
                    "Outbox cleanup deleted %d processed events", deleted
                )
        except Exception as e:
            logger.exception("Outbox cleanup failed: %s", e)

    async def _process_batch(self) -> None:
        """Process a batch of pending events."""

        start_time = datetime.now(timezone.utc)
        await self.outbox_publisher.process_pending_events(
            self.kafka_publisher, self.max_retries
        )
        processing_time = (
            datetime.now(timezone.utc) - start_time
        ).total_seconds()

        logger.debug(f"Processed pending events in {processing_time:.2f}s")

    async def process_once(self) -> None:
        """Process pending events once (for testing/manual runs)."""

        await self.outbox_publisher.process_pending_events(
            self.kafka_publisher, self.max_retries
        )


async def run_processor() -> None:
    """Run the outbox processor."""

    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("outbox-processor")
    install_asyncio_exception_handler("outbox-processor")
    log_startup_info(
        logger=logger, service_name="outbox-processor", config=config
    )

    if not config.db.database_url:
        logger.error("DATABASE_URL is required for outbox processor")
        return

    container = Container(config)
    outbox_publisher, kafka_publisher = container.build_outbox_deps()

    if not kafka_publisher:
        logger.error("Kafka is disabled, cannot run outbox processor")
        return

    # Create and start processor
    processor = OutboxProcessor(
        outbox_publisher=outbox_publisher,
        kafka_publisher=kafka_publisher,
        poll_interval=5.0,
        max_retries=3,
        outbox_config=config.outbox,
    )

    try:
        await processor.start()
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down outbox processor")
    finally:
        await processor.stop()
        stop_publisher = getattr(kafka_publisher, "stop", None)
        if callable(stop_publisher):
            try:
                await stop_publisher()
            except Exception:
                logger.exception("Failed to stop Kafka publisher")
        await container.dispose()


def main() -> None:
    """Entry point."""

    asyncio.run(run_processor())  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    main()
