"""Tests for Kafka consumer helpers."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from ugc_bot.application.messenger.dto import Keyboard, KeyboardKind
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
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
    InMemoryInteractionRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.kafka_consumer import (
    _commit_message_offset,
    _parse_order_id,
    _publish_dlq,
    _send_offer_to_blogger,
    _send_offer_via_client,
    _send_offers,
    _start_kafka_client_with_retry,
    main,
    run_consumer,
)


def test_parse_order_id_returns_none_for_unknown_event() -> None:
    """Ignore unrelated events."""
    assert _parse_order_id({"event": "other"}) is None
    assert _parse_order_id({"event": "order_activated"}) is None
    assert _parse_order_id({"event": "order_activated", "order_id": ""}) is None
    assert (
        _parse_order_id({"event": "order_activated", "order_id": "bad"}) is None
    )


def test_parse_order_id_returns_uuid_for_activation() -> None:
    """Extract order_id from order_activation payload."""
    got = _parse_order_id(
        {
            "event": "order_activated",
            "order_id": "00000000-0000-0000-0000-000000000999",
        }
    )
    assert got == UUID("00000000-0000-0000-0000-000000000999")


@pytest.mark.asyncio
async def test_send_offers_sends_messages() -> None:
    """Send offers to verified bloggers."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000900"),
        telegram_id="1",
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
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    await order_repo.save(order)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000902"),
        telegram_id="2",
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
            self.photos_sent: list[tuple[int, str, str]] = []

        async def send_message(
            self, chat_id: int, text: str, reply_markup=None, **kwargs
        ) -> None:  # type: ignore[no-untyped-def]
            self.sent.append((chat_id, text))

        async def send_photo(
            self,
            chat_id: int,
            photo: str,
            caption: str,
            reply_markup=None,
            **kwargs,
        ) -> None:  # type: ignore[no-untyped-def]
            self.photos_sent.append((chat_id, photo, caption))

    bot = FakeBot()
    messenger_client = TelegramMessengerClient(bot)
    await _send_offers(
        order.order_id,
        {"telegram": messenger_client},
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=1,
        retry_delay_seconds=0.0,
    )
    assert bot.sent
    assert not bot.photos_sent


@pytest.mark.asyncio
async def test_send_offers_with_photo_uses_send_photo() -> None:
    """When order has product_photo_file_id, send photo with caption."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000930"),
        telegram_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(advertiser)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000931"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
        product_photo_file_id="AgACAgIAAxkB_test_photo",
    )
    await order_repo.save(order)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000932"),
        telegram_id="2",
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
            self.photos_sent: list[tuple[int, str, str]] = []

        async def send_message(
            self, chat_id: int, text: str, reply_markup=None, **kwargs
        ) -> None:  # type: ignore[no-untyped-def]
            self.sent.append((chat_id, text))

        async def send_photo(
            self,
            chat_id: int,
            photo: str,
            caption: str,
            reply_markup=None,
            **kwargs,
        ) -> None:  # type: ignore[no-untyped-def]
            self.photos_sent.append((chat_id, photo, caption))

    bot = FakeBot()
    messenger_client = TelegramMessengerClient(bot)
    await _send_offers(
        order.order_id,
        {"telegram": messenger_client},
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=1,
        retry_delay_seconds=0.0,
    )
    assert bot.photos_sent
    assert len(bot.photos_sent) == 1
    chat_id, photo, caption = bot.photos_sent[0]
    assert chat_id == 2
    assert photo == "AgACAgIAAxkB_test_photo"
    assert "Новый заказ" in caption
    assert not bot.sent


@pytest.mark.asyncio
async def test_send_offers_returns_when_order_not_found() -> None:
    """_send_offers returns early when order is not found."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    order_id = UUID("00000000-0000-0000-0000-000000000999")
    bot = Mock(spec=["send_message"])
    bot.sent = []
    messenger_client = TelegramMessengerClient(bot)
    await _send_offers(
        order_id,
        {"telegram": messenger_client},
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
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    await order_repo.save(order)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    bot = Mock(spec=["send_message"])
    bot.sent = []
    messenger_client = TelegramMessengerClient(bot)
    await _send_offers(
        order.order_id,
        {"telegram": messenger_client},
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
        telegram_id="1",
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
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    await order_repo.save(order)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    with patch.object(
        OfferDispatchService,
        "dispatch",
        new_callable=AsyncMock,
        return_value=[],
    ):
        bot = Mock(spec=["send_message"])
        bot.sent = []
        messenger_client = TelegramMessengerClient(bot)
        await _send_offers(
            order.order_id,
            {"telegram": messenger_client},
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

    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.log_startup_info", _fake_startup_log
    )

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
    mock_container.build_bot_texts_service = lambda: None  # type: ignore[attr-defined]
    mock_container.build_user_role_service = lambda: None  # type: ignore[attr-defined]
    mock_container.dispose = AsyncMock()  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.Container",
        lambda _: mock_container,
    )

    send_called = {"value": False}

    async def fake_send(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        send_called["value"] = True

    monkeypatch.setattr("ugc_bot.kafka_consumer._send_offers", fake_send)

    session_closed = {"value": False}

    commit_called = {"value": False}

    class FakeConsumer:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False
            self._seen = 0

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

        async def commit(self, offsets=None) -> None:  # type: ignore[no-untyped-def]
            commit_called["value"] = True

        def __aiter__(self):
            return self

        async def __anext__(self):
            self._seen += 1
            if self._seen == 1:
                return SimpleNamespace(
                    topic="order_activated",
                    partition=0,
                    offset=0,
                    value={
                        "event": "order_activated",
                        "order_id": "00000000-0000-0000-0000-000000000999",
                    },
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
    assert commit_called["value"] is True
    assert fake_consumer.started is True
    assert fake_consumer.stopped is True
    assert fake_producer.started is True
    assert fake_producer.stopped is True
    assert session_closed["value"] is True


@pytest.mark.asyncio
async def test_publish_dlq_handles_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000910"),
        telegram_id="1",
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
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    await order_repo.save(order)
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000912"),
        telegram_id="2",
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
    messenger_client = TelegramMessengerClient(bot)
    await _send_offers(
        order.order_id,
        {"telegram": messenger_client},
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=2,
        retry_delay_seconds=0.0,
    )
    # Each offer sends 1 message (offer text includes blocks per TZ)
    # First attempt fails (1 call), retry succeeds (1 call) = 2 total
    assert bot.calls == 2


@pytest.mark.asyncio
async def test_send_offers_sends_to_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Send DLQ message after retries exhausted."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000920"),
        telegram_id="1",
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
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    await order_repo.save(order)
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000922"),
        telegram_id="2",
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

    messenger_client = TelegramMessengerClient(AlwaysFailBot())
    await _send_offers(
        order.order_id,
        {"telegram": messenger_client},
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=2,
        retry_delay_seconds=0.0,
    )
    assert published["value"] is True


@pytest.mark.asyncio
async def test_send_offers_user_blocked_bot_no_retry_no_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When user blocked the bot, do not retry and do not publish to DLQ."""
    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000923"),
        telegram_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(advertiser)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000924"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    await order_repo.save(order)
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000925"),
        telegram_id="2",
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

    blocked_error = TelegramForbiddenError(
        message="Forbidden: bot was blocked by the user",
        method=SendMessage(chat_id=0, text=""),
    )

    class BlockedUserBot:
        async def send_message(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise blocked_error

        async def send_photo(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise blocked_error

    published = {"value": False}

    async def fake_publish(_producer, _topic, _payload):  # type: ignore[no-untyped-def]
        published["value"] = True

    monkeypatch.setattr("ugc_bot.kafka_consumer._publish_dlq", fake_publish)

    messenger_client = TelegramMessengerClient(BlockedUserBot())
    await _send_offers(
        order.order_id,
        {"telegram": messenger_client},
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=3,
        retry_delay_seconds=0.0,
    )
    assert published["value"] is False


@pytest.mark.asyncio
async def test_start_kafka_client_with_retry_succeeds_after_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kafka client start retries on KafkaConnectionError, succeeds on retry."""
    from aiokafka.errors import KafkaConnectionError

    monkeypatch.setattr(
        "ugc_bot.kafka_consumer._KAFKA_BOOTSTRAP_MAX_RETRIES", 3
    )
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer._KAFKA_BOOTSTRAP_RETRY_DELAY_SECONDS", 0.01
    )

    calls = []

    async def flaky_start() -> None:
        calls.append(1)
        if len(calls) < 2:
            raise KafkaConnectionError("Unable to bootstrap")

    with patch("ugc_bot.kafka_consumer.asyncio.sleep", new_callable=AsyncMock):
        await _start_kafka_client_with_retry(flaky_start, "test client")

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_start_kafka_client_with_retry_raises_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kafka client start re-raises after exhausting retries."""
    from aiokafka.errors import KafkaConnectionError

    monkeypatch.setattr(
        "ugc_bot.kafka_consumer._KAFKA_BOOTSTRAP_MAX_RETRIES", 3
    )
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer._KAFKA_BOOTSTRAP_RETRY_DELAY_SECONDS", 0.01
    )

    async def always_fail() -> None:
        raise KafkaConnectionError("Unable to bootstrap")

    with (
        patch("ugc_bot.kafka_consumer.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(KafkaConnectionError),
    ):
        await _start_kafka_client_with_retry(always_fail, "test client")


@pytest.mark.asyncio
async def test_start_kafka_client_with_retry_raises_when_not_callable() -> None:
    """Raise TypeError when start_fn is not callable."""
    with pytest.raises(TypeError, match="start_fn must be callable"):
        await _start_kafka_client_with_retry("not_callable", "test client")


@pytest.mark.asyncio
async def test_send_offer_to_blogger_skips_when_blogger_is_advertiser() -> None:
    """Skip sending when blogger is the order advertiser."""
    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000940"),
        telegram_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000941"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    messenger = Mock()
    dispatch_service = Mock()
    await _send_offer_to_blogger(
        advertiser,
        order,
        "ACTIVE",
        {"telegram": messenger},
        dispatch_service,
        retries=1,
        retry_delay_seconds=0.0,
        dlq_producer=None,
        dlq_topic="dlq",
    )
    messenger.send_text.assert_not_called()
    messenger.send_photo.assert_not_called()


@pytest.mark.asyncio
async def test_send_offer_to_blogger_skips_when_no_messenger_ids() -> None:
    """Skip sending when blogger has no messenger IDs."""
    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000950"),
        telegram_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000951"),
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000952"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    messenger = Mock()
    dispatch_service = Mock()
    await _send_offer_to_blogger(
        blogger,
        order,
        "ACTIVE",
        {"telegram": messenger},
        dispatch_service,
        retries=1,
        retry_delay_seconds=0.0,
        dlq_producer=None,
        dlq_topic="dlq",
    )
    messenger.send_text.assert_not_called()
    messenger.send_photo.assert_not_called()


@pytest.mark.asyncio
async def test_commit_message_offset_returns_early_when_msg_incomplete() -> (
    None
):
    """Do not commit when msg has no topic, partition or offset."""
    consumer = AsyncMock()
    msg_missing_offset = SimpleNamespace(topic="t", partition=0, offset=None)
    await _commit_message_offset(consumer, msg_missing_offset)
    consumer.commit.assert_not_called()

    msg_missing_partition = SimpleNamespace(topic="t", partition=None, offset=0)
    await _commit_message_offset(consumer, msg_missing_partition)
    consumer.commit.assert_not_called()

    msg_missing_topic = SimpleNamespace(topic=None, partition=0, offset=0)
    await _commit_message_offset(consumer, msg_missing_topic)
    consumer.commit.assert_not_called()


@pytest.mark.asyncio
async def test_run_consumer_logs_exception_when_send_offers_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _send_offers raises, exception is logged and consumer stops."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "sqlite:///",
            "KAFKA_ENABLED": True,
            "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092",
            "KAFKA_TOPIC": "order_activated",
            "KAFKA_GROUP_ID": "ugc-bot",
            "KAFKA_DLQ_TOPIC": "dlq",
            "KAFKA_SEND_RETRIES": 2,
            "KAFKA_SEND_RETRY_DELAY_SECONDS": 0.0,
        }
    )
    monkeypatch.setattr("ugc_bot.kafka_consumer.load_config", lambda: config)
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.configure_logging", lambda *_, **__: None
    )
    mock_container = Mock()
    mock_container.build_offer_dispatch_service = Mock(return_value=Mock())
    mock_container.dispose = AsyncMock()
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.Container", lambda _: mock_container
    )

    async def send_offers_raises(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("send_offers failed")

    monkeypatch.setattr(
        "ugc_bot.kafka_consumer._send_offers", send_offers_raises
    )
    mock_logger = Mock()
    monkeypatch.setattr("ugc_bot.kafka_consumer.logger", mock_logger)

    class FakeConsumer:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False
            self._count = 0

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

        async def commit(self, offsets=None) -> None:  # type: ignore[no-untyped-def]
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            self._count += 1
            if self._count == 1:
                return SimpleNamespace(
                    topic="t",
                    partition=0,
                    offset=0,
                    value={
                        "event": "order_activated",
                        "order_id": "00000000-0000-0000-0000-000000000999",
                    },
                )
            raise asyncio.CancelledError

    class FakeProducer:
        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.session = Mock()
            self.session.close = AsyncMock()

    fake_consumer = FakeConsumer()
    fake_producer = FakeProducer()
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.AIOKafkaConsumer",
        lambda *a, **kw: fake_consumer,
    )
    monkeypatch.setattr(
        "ugc_bot.kafka_consumer.AIOKafkaProducer",
        lambda *a, **kw: fake_producer,
    )
    monkeypatch.setattr("ugc_bot.kafka_consumer.Bot", FakeBot)

    with pytest.raises(asyncio.CancelledError):
        await run_consumer()

    mock_logger.exception.assert_called()
    assert "Kafka message" in mock_logger.exception.call_args[0][0]


@pytest.mark.asyncio
async def test_send_offers_uses_blogger_locale_and_bot_texts_service() -> None:
    """_send_offers passes blogger.language as locale to offer sender."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )

    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000001001"),
        telegram_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(advertiser)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000001002"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    await order_repo.save(order)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000001003"),
        telegram_id="3",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger_en",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
        language="en",
    )
    await user_repo.save(blogger)
    await blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger_en",
            confirmed=True,
            city="Tbilisi",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Georgia",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )

    class FakeBotTexts:
        def __init__(self) -> None:
            self.called_with: list[tuple[list[str], str]] = []

        async def get_many(
            self, keys: list[str], locale: str
        ) -> dict[str, str]:
            self.called_with.append((keys, locale))
            return {}

    class FakeBot:
        def __init__(self) -> None:
            self.sent: list[tuple[int, str]] = []

        async def send_message(
            self, chat_id: int, text: str, reply_markup=None, **kwargs
        ) -> None:  # type: ignore[no-untyped-def]
            self.sent.append((chat_id, text))

    bot = FakeBot()
    messenger_client = TelegramMessengerClient(bot)
    fake_bot_texts = FakeBotTexts()
    await _send_offers(
        order.order_id,
        {"telegram": messenger_client},
        offer_service,
        dlq_producer=None,
        dlq_topic="dlq",
        retries=1,
        retry_delay_seconds=0.0,
        bot_texts_service=fake_bot_texts,
        default_locale="ru",
    )
    assert bot.sent
    # Verify bot_texts_service was called with the blogger's locale "en"
    locales_used = [locale for _, locale in fake_bot_texts.called_with]
    assert "en" in locales_used


@pytest.mark.asyncio
async def test_send_offer_to_blogger_includes_max_id_target() -> None:
    """_send_offer_to_blogger appends max_id target when blogger has max_id."""
    now = datetime.now(timezone.utc)
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000001100"),
        telegram_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000001101"),
        max_id="max-blogger-1",
        messenger_type=MessengerType.MAX,
        username="maxblogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000001102"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    max_messenger = Mock()
    max_messenger.send_text = AsyncMock()
    dispatch_service = Mock()
    dispatch_service.format_offer = AsyncMock(return_value="Offer text")
    dispatch_service.record_offer_dispatch = AsyncMock(return_value=Mock())
    dispatch_service.record_offer_sent = AsyncMock()
    with patch(
        "ugc_bot.kafka_consumer._send_offer_via_client", new_callable=AsyncMock
    ) as mock_send_via:
        await _send_offer_to_blogger(
            blogger,
            order,
            "ACTIVE",
            {"max": max_messenger},
            dispatch_service,
            retries=1,
            retry_delay_seconds=0.0,
            dlq_producer=None,
            dlq_topic="dlq",
        )
    mock_send_via.assert_called_once()
    call_kwargs = mock_send_via.call_args
    assert call_kwargs[0][0] == "max-blogger-1"


@pytest.mark.asyncio
async def test_send_offer_marks_user_bot_blocked_on_forbidden() -> None:
    """_send_offer_via_client sets BOT_BLOCKED on TelegramForbiddenError."""
    now = datetime.now(timezone.utc)
    user_repo = InMemoryUserRepository()
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        telegram_id="42",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(blogger)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000002"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000003"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    offer_dispatch_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        interaction_repo=InMemoryInteractionRepository(),
    )
    user_role_service = UserRoleService(user_repo=user_repo)

    blocked_error = TelegramForbiddenError(
        message="Forbidden: bot was blocked by the user",
        method=SendMessage(chat_id=0, text=""),
    )
    client = AsyncMock()
    client.send_text = AsyncMock(side_effect=blocked_error)

    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=[])

    result = await _send_offer_via_client(
        chat_id="42",
        messenger_client=client,
        offer_text="hi",
        reply_markup=keyboard,
        order=order,
        blogger=blogger,
        retries=1,
        retry_delay_seconds=0,
        offer_dispatch_service=offer_dispatch_service,
        dlq_producer=None,
        dlq_topic="dlq",
        messenger_label="telegram",
        user_role_service=user_role_service,
    )

    assert result is False
    updated = await user_repo.get_by_id(blogger.user_id)
    assert updated is not None
    assert updated.status == UserStatus.BOT_BLOCKED


@pytest.mark.asyncio
async def test_send_offer_to_blogger_skips_record_when_bot_blocked() -> None:
    """record_offer_sent not called when all sends fail (bot blocked)."""
    now = datetime.now(timezone.utc)
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000011"),
        telegram_id="99",
        messenger_type=MessengerType.TELEGRAM,
        username="blocked_blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000012"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000013"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    dispatch_service = Mock()
    dispatch_service.format_offer = AsyncMock(return_value="Offer text")
    dispatch_service.record_offer_sent = AsyncMock()
    tg_client = Mock()
    tg_client.send_text = AsyncMock()

    with patch(
        "ugc_bot.kafka_consumer._send_offer_via_client",
        new_callable=AsyncMock,
        return_value=False,
    ):
        await _send_offer_to_blogger(
            blogger,
            order,
            "ACTIVE",
            {"telegram": tg_client},
            dispatch_service,
            retries=1,
            retry_delay_seconds=0.0,
            dlq_producer=None,
            dlq_topic="dlq",
        )

    dispatch_service.record_offer_sent.assert_not_called()
