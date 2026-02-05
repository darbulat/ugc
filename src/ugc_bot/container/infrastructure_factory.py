"""Factory for creating infrastructure components."""

from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import async_sessionmaker

from ugc_bot.config import AppConfig
from ugc_bot.metrics.collector import MetricsCollector
from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    create_db_engine,
    create_session_factory,
)
from ugc_bot.infrastructure.redis_lock import IssueDescriptionLockManager


def create_session_factory_from_config(config: AppConfig):
    """Create async session factory from app config."""
    if not config.db.database_url:
        return None
    return create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )


def create_transaction_manager(
    session_factory: async_sessionmaker | None,
) -> SessionTransactionManager | None:
    """Create transaction manager from session factory."""
    if session_factory is None:
        return None
    return SessionTransactionManager(session_factory)


def build_admin_engine(config: AppConfig) -> Engine:
    """Create sync engine for SQLAdmin (pool_pre_ping)."""
    if not config.db.database_url:
        raise ValueError("DATABASE_URL is required for admin.")
    return create_db_engine(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )


def build_metrics_collector() -> MetricsCollector:
    """Create metrics collector."""
    return MetricsCollector()


def build_issue_lock_manager(config: AppConfig) -> IssueDescriptionLockManager:
    """Create lock manager for issue description (Redis or in-memory)."""
    redis_url = None
    if config.redis.use_redis_storage and config.redis.redis_url:
        redis_url = config.redis.redis_url
    return IssueDescriptionLockManager(redis_url=redis_url)


def build_instagram_api_client(config: AppConfig):
    """Create Instagram Graph API client if configured."""
    if (
        not config.instagram.instagram_access_token
        or not config.instagram.instagram_access_token.strip()
    ):
        return None
    from ugc_bot.infrastructure.instagram.graph_api_client import (
        HttpInstagramGraphApiClient,
    )

    return HttpInstagramGraphApiClient(
        access_token=config.instagram.instagram_access_token,
        base_url=config.instagram.instagram_api_base_url,
    )
