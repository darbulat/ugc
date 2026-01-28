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


def test_container_build_metrics_collector() -> None:
    """build_metrics_collector creates MetricsCollector instance."""

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    container = Container(config)
    metrics = container.build_metrics_collector()
    assert metrics is not None
    assert hasattr(metrics, "record_error")


def test_container_build_instagram_api_client_with_token() -> None:
    """build_instagram_api_client creates client when token is configured."""

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "INSTAGRAM_ACCESS_TOKEN": "test_token",
            "INSTAGRAM_API_BASE_URL": "https://api.instagram.com",
        }
    )
    container = Container(config)
    client = container.build_instagram_api_client()
    assert client is not None


def test_container_build_instagram_api_client_without_token() -> None:
    """build_instagram_api_client returns None when token is not configured."""

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "INSTAGRAM_ACCESS_TOKEN": "",  # Explicitly empty
        }
    )
    container = Container(config)
    client = container.build_instagram_api_client()
    assert client is None


def test_container_build_bot_services() -> None:
    """build_bot_services creates all services for bot dispatcher."""

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    container = Container(config)
    services = container.build_bot_services()

    assert "metrics_collector" in services
    assert "user_role_service" in services
    assert "blogger_registration_service" in services
    assert "advertiser_registration_service" in services
    assert "instagram_verification_service" in services
    assert "order_service" in services
    assert "offer_dispatch_service" in services
    assert "offer_response_service" in services
    assert "interaction_service" in services
    assert "payment_service" in services
    assert "contact_pricing_service" in services
    assert "profile_service" in services
    assert "complaint_service" in services


def test_container_build_bot_services_requires_database_url() -> None:
    """build_bot_services raises when DATABASE_URL is missing."""

    container = Container(_config(database_url=""))
    with pytest.raises(
        ValueError, match="DATABASE_URL is required for bot services\\."
    ):
        container.build_bot_services()
