"""Kafka publisher for order activation events."""

import asyncio
import json
import logging

from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]

from ugc_bot.application.ports import OrderActivationPublisher
from ugc_bot.domain.entities import Order

logger = logging.getLogger(__name__)


class KafkaOrderActivationPublisher(OrderActivationPublisher):
    """Publish order activation events to Kafka."""

    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self._topic = topic
        self._producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        )
        self._started = False
        self._start_lock = asyncio.Lock()

    async def _ensure_started(self) -> None:
        """Start the producer once (lazy-init)."""
        if self._started:  # pragma: no cover
            return
        async with self._start_lock:
            if self._started:  # pragma: no cover
                return
            await self._producer.start()
            self._started = True

    async def publish(self, order: Order) -> None:
        """Publish order activation message."""

        payload = {
            "event": "order_activated",
            "order_id": str(order.order_id),
            "advertiser_id": str(order.advertiser_id),
            "product_link": order.product_link,
            "price": order.price,
            "bloggers_needed": order.bloggers_needed,
            "status": order.status.value,
            "created_at": order.created_at.isoformat(),
        }
        try:
            await self._ensure_started()
            await self._producer.send_and_wait(self._topic, payload)
        except Exception:
            logger.exception("Failed to publish order activation to Kafka")

    async def stop(self) -> None:
        """Stop producer (best-effort)."""
        if not self._started:  # pragma: no cover
            return
        try:
            await self._producer.stop()
        finally:
            self._started = False


class NoopOrderActivationPublisher(OrderActivationPublisher):
    """No-op publisher used when Kafka is disabled."""

    async def publish(self, order: Order) -> None:
        """Skip publishing."""

        return
