"""Tests for Kafka publisher."""

import pytest

from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.kafka.publisher import (
    KafkaOrderActivationPublisher,
    NoopOrderActivationPublisher,
)
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID


def _order() -> Order:
    return Order(
        order_id=UUID("00000000-0000-0000-0000-000000000950"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000951"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )


@pytest.mark.asyncio
async def test_kafka_publisher_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish activation event."""

    sent = []

    class FakeProducer:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def send(self, topic, value):  # type: ignore[no-untyped-def]
            sent.append((topic, value))
            return SimpleNamespace()

        def flush(self):  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(
        "ugc_bot.infrastructure.kafka.publisher.KafkaProducer",
        FakeProducer,
    )

    publisher = KafkaOrderActivationPublisher(
        bootstrap_servers="kafka:9092",
        topic="order_activated",
    )
    await publisher.publish(_order())

    assert sent


@pytest.mark.asyncio
async def test_kafka_publisher_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swallow Kafka errors."""

    class FakeProducer:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def send(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def flush(self):  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(
        "ugc_bot.infrastructure.kafka.publisher.KafkaProducer",
        FakeProducer,
    )

    publisher = KafkaOrderActivationPublisher(
        bootstrap_servers="kafka:9092",
        topic="order_activated",
    )
    await publisher.publish(_order())


@pytest.mark.asyncio
async def test_noop_publisher() -> None:
    """Noop publisher does nothing."""

    publisher = NoopOrderActivationPublisher()
    await publisher.publish(_order())
