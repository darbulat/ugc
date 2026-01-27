"""Tests for dependency container error paths."""

import pytest

from ugc_bot.config import AppConfig
from ugc_bot.container import Container


def _config(database_url: str) -> AppConfig:
    """Build config for container tests."""

    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": database_url,
            "KAFKA_ENABLED": False,
        }
    )


def test_container_requires_database_url_for_db_dependent_methods() -> None:
    """Container raises clear errors when DATABASE_URL is missing."""

    container = Container(_config(database_url=""))

    assert container.session_factory is None
    assert container.transaction_manager is None

    with pytest.raises(ValueError, match="DATABASE_URL is required for admin\\."):
        container.get_admin_engine()

    with pytest.raises(
        ValueError, match="DATABASE_URL is required for repositories\\."
    ):
        container.build_repos()

    with pytest.raises(
        ValueError, match="DATABASE_URL is required for offer dispatch\\."
    ):
        container.build_offer_dispatch_service()

    with pytest.raises(
        ValueError, match="DATABASE_URL is required for admin services\\."
    ):
        container.build_admin_services()

    with pytest.raises(ValueError, match="DATABASE_URL is required for outbox\\."):
        container.build_outbox_deps()

    with pytest.raises(
        ValueError,
        match="DATABASE_URL is required for Instagram verification\\.",
    ):
        container.build_instagram_verification_service()


def test_container_build_outbox_deps_creates_kafka_publisher_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kafka publisher is constructed when Kafka is enabled."""

    class DummyKafkaPublisher:
        def __init__(self, bootstrap_servers: str, topic: str) -> None:
            self.bootstrap_servers = bootstrap_servers
            self.topic = topic

    monkeypatch.setattr(
        "ugc_bot.container.KafkaOrderActivationPublisher",
        DummyKafkaPublisher,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "KAFKA_ENABLED": True,
            "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
            "KAFKA_TOPIC": "order_activated",
        }
    )
    container = Container(config)

    _, kafka_publisher = container.build_outbox_deps()
    assert kafka_publisher is not None
    assert isinstance(kafka_publisher, DummyKafkaPublisher)
