"""Background processor for outbox events."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.ports import OrderActivationPublisher
from ugc_bot.config import load_config
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyOrderRepository,
    SqlAlchemyOutboxRepository,
)
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.infrastructure.kafka.publisher import KafkaOrderActivationPublisher
from ugc_bot.logging_setup import configure_logging

logger = logging.getLogger(__name__)


class OutboxProcessor:
    """Background processor for outbox events."""

    def __init__(
        self,
        outbox_publisher: OutboxPublisher,
        kafka_publisher: OrderActivationPublisher,
        poll_interval: float = 5.0,
        max_retries: int = 3,
    ):
        self.outbox_publisher = outbox_publisher
        self.kafka_publisher = kafka_publisher
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self._running = False
        self._task: Optional[asyncio.Task] = None

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
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Outbox processor stopped")

    async def _process_loop(self) -> None:
        """Main processing loop."""

        while self._running:
            try:
                await self._process_batch()
            except Exception as e:
                logger.exception(f"Error in outbox processing loop: {e}")

            await asyncio.sleep(self.poll_interval)

    async def _process_batch(self) -> None:
        """Process a batch of pending events."""

        start_time = datetime.now(timezone.utc)
        self.outbox_publisher.process_pending_events(
            self.kafka_publisher, self.max_retries
        )
        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.debug(f"Processed pending events in {processing_time:.2f}s")

    def process_once(self) -> None:
        """Process pending events once (for testing/manual runs)."""

        self.outbox_publisher.process_pending_events(
            self.kafka_publisher, self.max_retries
        )


async def run_processor() -> None:
    """Run the outbox processor."""

    config = load_config()
    configure_logging(config.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting outbox processor")

    if not config.database_url:
        logger.error("DATABASE_URL is required for outbox processor")
        return

    # Build dependencies
    session_factory = create_session_factory(config.database_url)
    order_repo = SqlAlchemyOrderRepository(session_factory=session_factory)
    outbox_repo = SqlAlchemyOutboxRepository(session_factory=session_factory)
    outbox_publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)

    # Create Kafka publisher
    kafka_publisher = (
        KafkaOrderActivationPublisher(
            bootstrap_servers=config.kafka_bootstrap_servers,
            topic=config.kafka_topic,
        )
        if config.kafka_enabled
        else None
    )

    if not kafka_publisher:
        logger.error("Kafka is disabled, cannot run outbox processor")
        return

    # Create and start processor
    processor = OutboxProcessor(
        outbox_publisher=outbox_publisher,
        kafka_publisher=kafka_publisher,
        poll_interval=5.0,
        max_retries=3,
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


def main() -> None:
    """Entry point."""

    asyncio.run(run_processor())


if __name__ == "__main__":
    main()
