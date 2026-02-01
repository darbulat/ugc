"""Tests for Kafka consumer helpers."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import pytest

from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import BloggerProfile, Order, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)
from ugc_bot.kafka_consumer import (
    _parse_order_id,
    _publish_dlq,
    _send_offers,
    main,
    run_consumer,
)


def test_parse_order_id_returns_none_for_unknown_event() -> None:
    """Ignore unrelated events."""
    assert _parse_order_id({"event": "other"}) is None
    assert _parse_order_id({"event": "order_activated"}) is None
    assert _parse_order_id({"event": "order_activated", "order_id": ""}) is None
    assert _parse_order_id({"event": "order_activated", "order_id": "bad"}) is None


def test_parse_order_id_returns_uuid_for_activation() -> None:
    """Extract order_id from order_activation payload."""
    got = _parse_order_id(
        {"event": "order_activated", "order_id": "00000000-0000-0000-0000-000000000999"}
    )
    assert got == UUID("00000000-0000-0000-0000-000000000999")


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
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(advertiser)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000901"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
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
    await order_repo.save(order)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000902"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(blogger)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )

    class FakeBot:
        def __init__(self) -> None:
            self.sent: list[tuple[int, str]] = []

        async def send_message(
            self, chat_id: int, text: str, reply_markup=None, **kwargs
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


@pytest.mark.asyncio
async def test_send_offers_returns_when_order_not_found() -> None:
    """_send_offers returns early when order is not found."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000999")
    bot = Mock(spec=["send_message"])
    bot.sent = []
    await _send_offers(
        order_id,
        bot,
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=1,
        retry_delay_seconds=0.0,
    )
    assert len(bot.sent) == 0


@pytest.mark.asyncio
async def test_send_offers_returns_when_advertiser_not_found() -> None:
    """_send_offers returns early when advertiser is not found."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    now = datetime.now(timezone.utc)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000901"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000900"),
        order_type=OrderType.UGC_ONLY,
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
    await order_repo.save(order)
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )
    bot = Mock(spec=["send_message"])
    bot.sent = []
    await _send_offers(
        order.order_id,
        bot,
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=1,
        retry_delay_seconds=0.0,
    )
    assert len(bot.sent) == 0


@pytest.mark.asyncio
async def test_send_offers_returns_when_no_verified_bloggers() -> None:
    """_send_offers returns early when dispatch returns no bloggers."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000900"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(advertiser)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000901"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
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
    await order_repo.save(order)
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )
    with patch.object(
        OfferDispatchService, "dispatch", new_callable=AsyncMock, return_value=[]
    ):
        bot = Mock(spec=["send_message"])
        bot.sent = []
        await _send_offers(
            order.order_id,
            bot,
            offer_service,
            dlq_producer=None,
            dlq_topic="dlq",
            retries=1,
            retry_delay_seconds=0.0,
        )
        assert len(bot.sent) == 0


def test_main_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exit early when Kafka disabled."""

    config = AppConfig.model_validate(
        {"BOT_TOKEN": "token", "DATABASE_URL": "db", "KAFKA_ENABLED": False}
    )
    monkeypatch.setattr("ugc_bot.kafka_consumer.load_config", lambda: config)
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.configure_logging", lambda *_, **__: None
    )
    startup_called: dict[str, object] = {}

    def _fake_startup_log(**kwargs):  # type: ignore[no-untyped-def]
        startup_called.update(kwargs)

    monkeypatch.setattr("ugc_bot.kafka_consumer.log_startup_info", _fake_startup_log)

    main()
    assert startup_called.get("service_name") == "kafka-consumer"


@pytest.mark.asyncio
async def test_run_consumer_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_consumer exits early when DATABASE_URL is empty."""

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "",
            "KAFKA_ENABLED": True,
            "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092",
            "KAFKA_TOPIC": "t",
            "KAFKA_GROUP_ID": "g",
        }
    )
    monkeypatch.setattr("ugc_bot.kafka_consumer.load_config", lambda: config)
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.configure_logging", lambda *_, **__: None
    )
    mock_logger = Mock()
    monkeypatch.setattr("ugc_bot.kafka_consumer.logger", mock_logger)

    await run_consumer()

    mock_logger.error.assert_called_once()
    assert "DATABASE_URL" in mock_logger.error.call_args[0][0]


@pytest.mark.asyncio
async def test_run_consumer_processes_activation_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_consumer processes activation message and invokes _send_offers."""

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "sqlite:///",
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
        "ugc_bot.kafka_consumer.configure_logging", lambda *_, **__: None
    )

    mock_offer = type("Offer", (), {})()
    mock_container = type("Container", (), {})()
    mock_container.build_offer_dispatch_service = lambda: mock_offer  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.Container",
        lambda _: mock_container,
    )

    send_called = {"value": False}

    async def fake_send(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        send_called["value"] = True

    monkeypatch.setattr("ugc_bot.kafka_consumer._send_offers", fake_send)

    session_closed = {"value": False}

    class FakeConsumer:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False
            self._seen = 0

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

        def __aiter__(self):
            return self

        async def __anext__(self):
            self._seen += 1
            if self._seen == 1:
                return SimpleNamespace(
                    value={
                        "event": "order_activated",
                        "order_id": "00000000-0000-0000-0000-000000000999",
                    }
                )
            raise asyncio.CancelledError

    class FakeProducer:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

        async def send_and_wait(self, *_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            return None

    class FakeSession:
        async def close(self) -> None:
            session_closed["value"] = True

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.session = FakeSession()

    fake_consumer = FakeConsumer()
    fake_producer = FakeProducer()
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.AIOKafkaConsumer",
        lambda *args, **kwargs: fake_consumer,
    )
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.AIOKafkaProducer",
        lambda *args, **kwargs: fake_producer,
    )
    monkeypatch.setattr("ugc_bot.kafka_consumer.Bot", FakeBot)

    with pytest.raises(asyncio.CancelledError):
        await run_consumer()

    assert send_called["value"] is True
    assert fake_consumer.started is True
    assert fake_consumer.stopped is True
    assert fake_producer.started is True
    assert fake_producer.stopped is True
    assert session_closed["value"] is True


@pytest.mark.asyncio
async def test_publish_dlq_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """DLQ publisher should swallow errors."""

    class FakeProducer:
        async def send_and_wait(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    await _publish_dlq(FakeProducer(), "dlq", {"event": "offer_send_failed"})


@pytest.mark.asyncio
async def test_publish_dlq_none_producer() -> None:
    """_publish_dlq returns without calling send when producer is None."""

    await _publish_dlq(None, "dlq_topic", {"event": "x"})  # no-op, no raise


@pytest.mark.asyncio
async def test_publish_dlq_success() -> None:
    """_publish_dlq calls send_and_wait when producer is not None."""

    producer = Mock()
    producer.send_and_wait = AsyncMock()

    await _publish_dlq(producer, "dlq_topic", {"event": "offer_send_failed"})

    producer.send_and_wait.assert_awaited_once_with(
        "dlq_topic", {"event": "offer_send_failed"}
    )


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
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(advertiser)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000911"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
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
    await order_repo.save(order)
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000912"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(blogger)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
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
    # Each offer sends 1 message (offer text includes blocks; no separate warning per TZ)
    # First attempt fails (1 call), retry succeeds (1 call) = 2 total
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
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(advertiser)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000921"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
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
    await order_repo.save(order)
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000922"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(blogger)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )

    class AlwaysFailBot:
        async def send_message(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    published = {"value": False}

    async def fake_publish(_producer, _topic, _payload):  # type: ignore[no-untyped-def]
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
