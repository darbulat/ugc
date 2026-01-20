"""Kafka publisher for order activation events."""

import json
import logging

from kafka import KafkaProducer  # type: ignore[import-untyped]

from ugc_bot.application.ports import OrderActivationPublisher
from ugc_bot.domain.entities import Order


logger = logging.getLogger(__name__)


class KafkaOrderActivationPublisher(OrderActivationPublisher):
    """Publish order activation events to Kafka."""

    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self._topic = topic
        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        )

    def publish(self, order: Order) -> None:
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
            future = self._producer.send(self._topic, payload)
            # Ensure send errors are surfaced to caller.
            future.get(timeout=10)
        except Exception:
            logger.exception("Failed to publish order activation to Kafka")
            raise


class NoopOrderActivationPublisher(OrderActivationPublisher):
    """No-op publisher used when Kafka is disabled."""

    def publish(self, order: Order) -> None:
        """Skip publishing."""

        return None
