"""Kafka publisher for order activation events."""

import json
import logging
from typing import Any

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
            future: Any = self._producer.send(self._topic, payload)

            # Ensure send errors are surfaced to caller when possible.
            # In tests we often use a stub producer that returns a simple object.
            get = getattr(future, "get", None)
            if callable(get):
                get(timeout=10)

            # Keep previous behaviour (tests expect flush to be called/available).
            self._producer.flush()
        except Exception:
            # For this project we intentionally keep publisher best-effort:
            # log the failure, but do not break the use-case.
            logger.exception("Failed to publish order activation to Kafka")
            return None


class NoopOrderActivationPublisher(OrderActivationPublisher):
    """No-op publisher used when Kafka is disabled."""

    def publish(self, order: Order) -> None:
        """Skip publishing."""

        return None
