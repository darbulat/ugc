"""Factory for creating infrastructure components."""

from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import async_sessionmaker

from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    create_db_engine,
    create_session_factory,
)
from ugc_bot.infrastructure.redis_lock import IssueDescriptionLockManager
from ugc_bot.metrics.collector import MetricsCollector


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


def build_offer_response_rate_limiter(config: AppConfig):
    """Create rate limiter for offer responses (Redis or in-memory)."""
    from ugc_bot.bot.handlers.utils import RateLimiter
    from ugc_bot.infrastructure.redis_rate_limiter import RedisRateLimiter

    if config.redis.use_redis_storage and config.redis.redis_url:
        return RedisRateLimiter(
            redis_url=config.redis.redis_url,
            limit=5,
            window_seconds=10.0,
        )
    return RateLimiter(limit=5, window_seconds=10.0)


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

    business_id = config.instagram.instagram_business_account_id.strip() or None
    business_token = (
        config.instagram.instagram_business_access_token.strip() or None
    )
    return HttpInstagramGraphApiClient(
        access_token=config.instagram.instagram_access_token,
        base_url=config.instagram.instagram_api_base_url,
        business_account_id=business_id,
        business_access_token=business_token,
    )


def build_rapid_api_client(config: AppConfig):
    """Create Rapid API Instagram client if key and host configured."""
    ig = config.instagram
    if not ig.rapidapi_key or not ig.rapidapi_key.strip():
        return None
    if not ig.rapidapi_instagram_host or not ig.rapidapi_instagram_host.strip():
        return None
    from ugc_bot.infrastructure.instagram.rapid_api_client import (
        HttpInstagramRapidApiClient,
    )

    return HttpInstagramRapidApiClient(
        api_key=ig.rapidapi_key,
        host=ig.rapidapi_instagram_host,
    )
