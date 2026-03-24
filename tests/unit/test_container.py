"""Tests for dependency container error paths."""

from unittest.mock import AsyncMock, Mock

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


def test_container_build_instagram_stats_provider_client_single() -> None:
    """build_instagram_stats_collector_scheduler_deps uses ScrapeCreators."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "SCRAPECREATORS_API_KEY": "sk",
        }
    )
    container = Container(config)
    deps = container.build_instagram_stats_collector_scheduler_deps()
    assert deps.get("instagram_stats_collector_service") is not None
    assert deps.get("interval_seconds") is not None


def test_container_build_instagram_stats_provider_client_none() -> None:
    """When no ScrapeCreators config, scheduler deps built with None client."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "SCRAPECREATORS_API_KEY": "",
        }
    )
    container = Container(config)
    deps = container.build_instagram_stats_collector_scheduler_deps()
    assert "instagram_stats_collector_service" in deps
    assert deps.get("interval_seconds") is not None


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


def test_container_build_instagram_stats_provider_returns_scrapecreators() -> (
    None
):
    """build_instagram_stats_provider_client returns ScrapeCreators client."""
    from ugc_bot.infrastructure.instagram.scrapecreators_client import (
        ScrapeCreatorsProfileClient,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "SCRAPECREATORS_API_KEY": "sk",
        }
    )
    client = infrastructure_factory.build_instagram_stats_provider_client(
        config
    )
    assert client is not None
    assert isinstance(client, ScrapeCreatorsProfileClient)


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


def test_container_build_instagram_stats_collector_scheduler_deps() -> None:
    """Stats collector scheduler deps include service and interval."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    container = Container(config)
    deps = container.build_instagram_stats_collector_scheduler_deps()
    assert "instagram_stats_collector_service" in deps
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
    assert "manager_service" in services
    assert "manager_order_repo" in services


def test_container_build_bot_texts_service() -> None:
    """build_bot_texts_service creates BotTextsService instance."""
    from ugc_bot.application.services.bot_texts_service import BotTextsService

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    container = Container(config)
    service = container.build_bot_texts_service()
    assert isinstance(service, BotTextsService)


def test_container_build_manager_service() -> None:
    """build_manager_service creates ManagerService instance."""
    from ugc_bot.application.services.manager_service import ManagerService

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    container = Container(config)
    service = container.build_manager_service()
    assert isinstance(service, ManagerService)


def test_container_build_bot_services_requires_database_url() -> None:
    """build_bot_services raises when DATABASE_URL is missing."""

    container = Container(_config(database_url=""))
    with pytest.raises(
        ValueError, match="DATABASE_URL is required for bot services\\."
    ):
        container.build_bot_services()


def test_container_build_instagram_stats_scheduler_deps() -> None:
    """build_instagram_stats_scheduler_deps returns service and interval."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "INSTAGRAM_ACCESS_TOKEN": "test_access_token",
            "INSTAGRAM_API_BASE_URL": "https://api.instagram.com",
        }
    )
    container = Container(config)
    deps = container.build_instagram_stats_scheduler_deps()
    assert "instagram_stats_update_service" in deps
    assert "interval_seconds" in deps


def test_container_build_geocoder_returns_geocoder_port() -> None:
    """build_geocoder returns an object with geocode method (GeocoderPort)."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    container = Container(config)
    geocoder = container.build_geocoder()
    assert geocoder is not None
    assert hasattr(geocoder, "geocode")


def test_build_aiograpi_fetcher_returns_none_on_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_aiograpi_fetcher returns None when aiograpi is not importable."""
    import builtins

    from ugc_bot.config import AppConfig
    from ugc_bot.container import service_factory

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "INSTAGRAM_STATS_AIOGRAPI_USERNAME": "user",
            "INSTAGRAM_STATS_AIOGRAPI_PASSWORD": "pass",
        }
    )
    original_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if "aiograpi" in name:
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    result = service_factory._build_aiograpi_fetcher(config)
    assert result is None


def test_container_build_user_role_service() -> None:
    """build_user_role_service creates UserRoleService instance."""
    from ugc_bot.application.services.user_role_service import UserRoleService

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    container = Container(config)
    service = container.build_user_role_service()
    assert isinstance(service, UserRoleService)


def test_container_build_referral_reconciliation_deps() -> None:
    """build_referral_reconciliation_deps returns expected deps dict."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    container = Container(config)
    deps = container.build_referral_reconciliation_deps()
    assert isinstance(deps, dict)


def test_build_offer_response_rate_limiter_without_redis() -> None:
    """Rate limiter falls back to in-memory when Redis is not configured."""
    from ugc_bot.bot.handlers.utils import RateLimiter

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "USE_REDIS_STORAGE": False,
        }
    )
    limiter = infrastructure_factory.build_offer_response_rate_limiter(config)
    assert isinstance(limiter, RateLimiter)


def test_build_geocode_public_rate_limiter_without_redis() -> None:
    """Geocode rate limiter falls back to in-memory without Redis."""
    from ugc_bot.bot.handlers.utils import RateLimiter

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "USE_REDIS_STORAGE": False,
        }
    )
    limiter = infrastructure_factory.build_geocode_public_rate_limiter(config)
    assert isinstance(limiter, RateLimiter)


def test_build_repos_uses_redis_verification_when_configured() -> None:
    """instagram_repo uses Redis when USE_REDIS_STORAGE is True."""
    from ugc_bot.infrastructure.redis_verification import (
        RedisInstagramVerificationRepository,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "USE_REDIS_STORAGE": True,
            "REDIS_URL": "redis://localhost:6379/1",
        }
    )
    container = Container(config)
    repos = container.build_repos()
    assert isinstance(
        repos["instagram_repo"], RedisInstagramVerificationRepository
    )


def test_build_repos_uses_sql_verification_without_redis() -> None:
    """instagram_repo uses SQL when USE_REDIS_STORAGE is False."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyInstagramVerificationRepository,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "USE_REDIS_STORAGE": False,
        }
    )
    container = Container(config)
    repos = container.build_repos()
    assert isinstance(
        repos["instagram_repo"], SqlAlchemyInstagramVerificationRepository
    )


def test_build_exchange_rate_service_without_redis() -> None:
    """build_exchange_rate_service returns None when Redis URL is empty."""
    from ugc_bot.container import service_factory

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
            "REDIS_URL": "",
        }
    )
    result = service_factory.build_exchange_rate_service(config)
    assert result is None


@pytest.mark.asyncio
async def test_container_dispose_calls_engine_dispose() -> None:
    """Container.dispose() disposes the async engine."""
    mock_engine = AsyncMock()
    mock_session_factory = Mock()
    mock_session_factory.kw = {"bind": mock_engine}

    config = _config("sqlite:///test.db")
    container = Container(config)
    container._session_factory = mock_session_factory

    await container.dispose()
    mock_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_container_dispose_no_session_factory() -> None:
    """Container.dispose() is safe when session_factory is None."""
    config = _config("")
    container = Container(config)
    container._session_factory = None
    await container.dispose()  # Should not raise
