"""Tests for Kafka consumer helpers."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import BloggerProfile, Order, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OrderStatus,
    UserRole,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)
from ugc_bot.kafka_consumer import _handle_message, _publish_dlq, _send_offers, main


def test_handle_message_skips_unknown_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ignore unrelated events."""

    called = {"value": False}

    async def fake_send(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        called["value"] = True

    monkeypatch.setattr("ugc_bot.kafka_consumer._send_offers", fake_send)

    _handle_message(
        {"event": "other"},
        bot_token="token",
        offer_dispatch_service=None,  # type: ignore[arg-type]
        dlq_producer=None,
        dlq_topic="dlq",
        retries=1,
        retry_delay_seconds=0.0,
    )
    assert called["value"] is False


def test_handle_message_invokes_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """Process activation event."""

    called = {"value": False}

    async def fake_send(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        called["value"] = True

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token
            self.session = self

        async def close(self) -> None:  # type: ignore[no-untyped-def]
            return None

    def fake_run(coro):  # type: ignore[no-untyped-def]
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    monkeypatch.setattr("ugc_bot.kafka_consumer.Bot", FakeBot)
    monkeypatch.setattr("ugc_bot.kafka_consumer._send_offers", fake_send)
    monkeypatch.setattr("ugc_bot.kafka_consumer.asyncio.run", fake_run)

    _handle_message(
        {
            "event": "order_activated",
            "order_id": "00000000-0000-0000-0000-000000000999",
        },
        bot_token="token",
        offer_dispatch_service=None,  # type: ignore[arg-type]
        dlq_producer=None,
        dlq_topic="dlq",
        retries=1,
        retry_delay_seconds=0.0,
    )

    assert called["value"] is True


@pytest.mark.asyncio
async def test_send_offers_sends_messages() -> None:
    """Send offers to verified bloggers."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )

    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000900"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    user_repo.save(advertiser)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000901"),
        advertiser_id=advertiser.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        contacts_sent_at=None,
    )
    order_repo.save(order)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000902"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    user_repo.save(blogger)
    blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=now,
        )
    )

    class FakeBot:
        def __init__(self) -> None:
            self.sent: list[tuple[int, str]] = []

        async def send_message(
            self, chat_id: int, text: str, reply_markup=None
        ) -> None:  # type: ignore[no-untyped-def]
            self.sent.append((chat_id, text))

    bot = FakeBot()
    await _send_offers(
        order.order_id,
        bot,
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=1,
        retry_delay_seconds=0.0,
    )
    assert bot.sent


def test_main_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exit early when Kafka disabled."""

    config = AppConfig.model_validate(
        {"BOT_TOKEN": "token", "DATABASE_URL": "db", "KAFKA_ENABLED": False}
    )
    monkeypatch.setattr("ugc_bot.kafka_consumer.load_config", lambda: config)
    called = {"value": False}

    def fake_factory(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        called["value"] = True
        return None

    monkeypatch.setattr("ugc_bot.kafka_consumer.create_session_factory", fake_factory)

    main()
    assert called["value"] is False


def test_main_consumes_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Consume events when Kafka enabled."""

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "db",
            "KAFKA_ENABLED": True,
            "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092",
            "KAFKA_TOPIC": "order_activated",
            "KAFKA_GROUP_ID": "ugc-bot",
            "KAFKA_DLQ_TOPIC": "order_activated_dlq",
            "KAFKA_SEND_RETRIES": 2,
            "KAFKA_SEND_RETRY_DELAY_SECONDS": 0.0,
        }
    )
    monkeypatch.setattr("ugc_bot.kafka_consumer.load_config", lambda: config)
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.create_session_factory", lambda *_: None
    )
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.KafkaProducer",
        lambda *_args, **_kwargs: object(),
    )

    class FakeConsumer:
        def __iter__(self):  # type: ignore[no-untyped-def]
            return iter(
                [
                    SimpleNamespace(
                        value={
                            "event": "order_activated",
                            "order_id": "00000000-0000-0000-0000-000000000999",
                        }
                    )
                ]
            )

    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.KafkaConsumer", lambda *_args, **_kwargs: FakeConsumer()
    )

    called = {"value": False}

    def fake_handle(_data, _token, _service, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        called["value"] = True

    monkeypatch.setattr("ugc_bot.kafka_consumer._handle_message", fake_handle)

    main()
    assert called["value"] is True


def test_publish_dlq_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """DLQ publisher should swallow errors."""

    class FakeProducer:
        def send(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def flush(self):  # type: ignore[no-untyped-def]
            return None

    _publish_dlq(FakeProducer(), "dlq", {"event": "offer_send_failed"})


@pytest.mark.asyncio
async def test_send_offers_retries_then_succeeds() -> None:
    """Retry sending offer messages before succeeding."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )
    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000910"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    user_repo.save(advertiser)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000911"),
        advertiser_id=advertiser.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        contacts_sent_at=None,
    )
    order_repo.save(order)
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000912"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    user_repo.save(blogger)
    blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=now,
        )
    )

    class FlakyBot:
        def __init__(self) -> None:
            self.calls = 0

        async def send_message(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls < 2:
                raise RuntimeError("temp")

    bot = FlakyBot()
    await _send_offers(
        order.order_id,
        bot,
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=2,
        retry_delay_seconds=0.0,
    )
    assert bot.calls == 2


@pytest.mark.asyncio
async def test_send_offers_sends_to_dlq(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send DLQ message after retries exhausted."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )
    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000920"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    user_repo.save(advertiser)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000921"),
        advertiser_id=advertiser.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        contacts_sent_at=None,
    )
    order_repo.save(order)
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000922"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    user_repo.save(blogger)
    blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=now,
        )
    )

    class AlwaysFailBot:
        async def send_message(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    published = {"value": False}

    def fake_publish(_producer, _topic, _payload):  # type: ignore[no-untyped-def]
        published["value"] = True

    monkeypatch.setattr("ugc_bot.kafka_consumer._publish_dlq", fake_publish)

    await _send_offers(
        order.order_id,
        AlwaysFailBot(),
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=2,
        retry_delay_seconds=0.0,
    )
    assert published["value"] is True
