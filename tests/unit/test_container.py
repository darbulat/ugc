"""Tests for dependency container error paths."""

import pytest

from ugc_bot.config import AppConfig
from ugc_bot.container import Container, infrastructure_factory


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

    with pytest.raises(
        ValueError, match="DATABASE_URL is required for admin\\."
    ):
        container.get_admin_engine()

    with pytest.raises(
        ValueError, match="DATABASE_URL is required for repositories\\."
    ):
        container.build_repos()

    with pytest.raises(
        ValueError, match="DATABASE_URL is required for repositories\\."
    ):
        container.build_offer_dispatch_service()

    with pytest.raises(
        ValueError, match="DATABASE_URL is required for repositories\\."
    ):
        container.build_admin_services()

    with pytest.raises(
        ValueError, match="DATABASE_URL is required for repositories\\."
    ):
        container.build_outbox_deps()

    with pytest.raises(
        ValueError, match="DATABASE_URL is required for repositories\\."
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
        "ugc_bot.container.service_factory.KafkaOrderActivationPublisher",
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


def test_container_build_issue_lock_manager_with_redis() -> None:
    """build_issue_lock_manager uses Redis URL when Redis storage is enabled."""

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "USE_REDIS_STORAGE": True,
            "REDIS_URL": "redis://localhost:6379/1",
        }
    )
    container = Container(config)
    manager = container.build_issue_lock_manager()
    assert manager is not None
    assert manager._redis_url == "redis://localhost:6379/1"


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


def test_container_build_rapid_api_client_when_configured() -> None:
    """build_rapid_api_client returns client when key and host are set."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "RAPIDAPI_KEY": "key",
            "RAPIDAPI_INSTAGRAM_HOST": "instagram-v2",
        }
    )
    container = Container(config)
    client = container.build_rapid_api_client()
    assert client is not None


def test_container_build_rapid_api_client_without_key() -> None:
    """build_rapid_api_client returns None when key or host is empty."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "RAPIDAPI_KEY": "",
            "RAPIDAPI_INSTAGRAM_HOST": "host",
        }
    )
    container = Container(config)
    assert container.build_rapid_api_client() is None


def test_container_build_instagram_stats_provider_client_single() -> None:
    """build_instagram_rapid_stats_scheduler_deps uses provider client."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "RAPIDAPI_KEY": "key",
            "RAPIDAPI_INSTAGRAM_HOST": "instagram-v2",
        }
    )
    container = Container(config)
    deps = container.build_instagram_rapid_stats_scheduler_deps()
    assert deps.get("instagram_rapid_stats_collector_service") is not None
    assert deps.get("interval_seconds") is not None


def test_container_build_instagram_stats_provider_client_none() -> None:
    """When no Rapid API config, scheduler deps still built with None client."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "RAPIDAPI_KEY": "",
            "RAPIDAPI_INSTAGRAM_HOST": "",
        }
    )
    container = Container(config)
    deps = container.build_instagram_rapid_stats_scheduler_deps()
    assert "instagram_rapid_stats_collector_service" in deps
    assert deps.get("interval_seconds") is not None


def test_container_build_instagram_stats_provider_client_multi() -> None:
    """With provider 1 and 2 configured, multi-provider client is built."""
    from ugc_bot.infrastructure.instagram.rapid_api_client import (
        MultiProviderInstagramStatsClient,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "RAPIDAPI_KEY": "key1",
            "RAPIDAPI_INSTAGRAM_HOST": "host1",
            "RAPIDAPI_KEY_2": "key2",
            "RAPIDAPI_INSTAGRAM_HOST_2": "host2",
        }
    )
    client = infrastructure_factory.build_instagram_stats_provider_client(
        config
    )
    assert client is not None
    assert isinstance(client, MultiProviderInstagramStatsClient)


def test_container_build_instagram_stats_provider_client_web_only() -> None:
    """With only INSTAGRAM_WEB_PROFILE_ENABLED=true, web client is built."""
    from ugc_bot.infrastructure.instagram.rapid_api_client import (
        SingleProviderWrapper,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "INSTAGRAM_WEB_PROFILE_ENABLED": True,
        }
    )
    client = infrastructure_factory.build_instagram_stats_provider_client(
        config
    )
    assert client is not None
    assert isinstance(client, SingleProviderWrapper)


def test_build_scrapecreators_client_none_when_key_empty() -> None:
    """build_scrapecreators_profile_client returns None when API key empty."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "SCRAPECREATORS_API_KEY": "",
        }
    )
    client = infrastructure_factory.build_scrapecreators_profile_client(config)
    assert client is None


def test_container_build_scrapecreators_profile_client_when_key_set() -> None:
    """build_scrapecreators_profile_client returns client when API key set."""
    from ugc_bot.infrastructure.instagram.scrapecreators_client import (
        ScrapeCreatorsProfileClient,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "SCRAPECREATORS_API_KEY": "sk_test",
        }
    )
    client = infrastructure_factory.build_scrapecreators_profile_client(config)
    assert client is not None
    assert isinstance(client, ScrapeCreatorsProfileClient)


def test_container_build_instagram_stats_provider_includes_scrapecreators() -> (
    None
):
    """With only SCRAPECREATORS_API_KEY set, provider is ScrapeCreators."""
    from ugc_bot.infrastructure.instagram.rapid_api_client import (
        SingleProviderWrapper,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "INSTAGRAM_WEB_PROFILE_ENABLED": False,
            "SCRAPECREATORS_API_KEY": "sk",
        }
    )
    client = infrastructure_factory.build_instagram_stats_provider_client(
        config
    )
    assert client is not None
    assert isinstance(client, SingleProviderWrapper)


def test_container_build_feedback_scheduler_deps() -> None:
    """build_feedback_scheduler_deps returns deps with interaction_repo."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    container = Container(config)
    deps = container.build_feedback_scheduler_deps()
    assert "interaction_repo" in deps
    assert "interaction_service" in deps
    assert "interval_seconds" not in deps


def test_container_build_instagram_rapid_stats_scheduler_deps() -> None:
    """Rapid stats scheduler deps include service and interval."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    container = Container(config)
    deps = container.build_instagram_rapid_stats_scheduler_deps()
    assert "instagram_rapid_stats_collector_service" in deps
    assert "interval_seconds" in deps
    assert deps["interval_seconds"] == 86400


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
    assert "offer_response_rate_limiter" in services
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
