"""Tests for Kafka publisher."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus, OrderType
from ugc_bot.infrastructure.kafka.publisher import (
    KafkaOrderActivationPublisher,
    NoopOrderActivationPublisher,
)


def _order() -> Order:
    return Order(
        order_id=UUID("00000000-0000-0000-0000-000000000950"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000951"),
        order_type=OrderType.UGC_ONLY,
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

    created: dict[str, object] = {}
    sent: list[tuple[str, object]] = []

    class FakeProducer:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False

        async def start(self) -> None:
            self.started = True

        async def send_and_wait(self, topic, value):  # type: ignore[no-untyped-def]
            sent.append((topic, value))
            return None

        async def stop(self) -> None:
            self.stopped = True

    def fake_producer_factory(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        created["producer"] = FakeProducer()
        return created["producer"]

    monkeypatch.setattr(
        "ugc_bot.infrastructure.kafka.publisher.AIOKafkaProducer",
        fake_producer_factory,
    )

    publisher = KafkaOrderActivationPublisher(
        bootstrap_servers="kafka:9092",
        topic="order_activated",
    )
    await publisher.publish(_order())

    assert sent
    producer = created["producer"]
    assert isinstance(producer, FakeProducer)
    assert producer.started is True

    await publisher.stop()
    assert producer.stopped is True


@pytest.mark.asyncio
async def test_kafka_publisher_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swallow Kafka errors."""

    created: dict[str, object] = {}

    class FakeProducer:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False

        async def start(self) -> None:
            self.started = True

        async def send_and_wait(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        async def stop(self) -> None:
            self.stopped = True

    def fake_producer_factory(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        created["producer"] = FakeProducer()
        return created["producer"]

    monkeypatch.setattr(
        "ugc_bot.infrastructure.kafka.publisher.AIOKafkaProducer",
        fake_producer_factory,
    )

    publisher = KafkaOrderActivationPublisher(
        bootstrap_servers="kafka:9092",
        topic="order_activated",
    )
    await publisher.publish(_order())

    producer = created["producer"]
    assert isinstance(producer, FakeProducer)
    assert producer.started is True

    await publisher.stop()
    assert producer.stopped is True


@pytest.mark.asyncio
async def test_noop_publisher() -> None:
    """Noop publisher does nothing."""

    publisher = NoopOrderActivationPublisher()
    await publisher.publish(_order())
