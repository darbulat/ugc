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


def _build_one_rapid_client(
    api_key: str,
    host: str,
    path: str,
    param_style: str,
):
    """Build one HttpInstagramRapidApiClient if key and host are set."""
    from ugc_bot.infrastructure.instagram.rapid_api_client import (
        HttpInstagramRapidApiClient,
    )

    if not (api_key or "").strip() or not (host or "").strip():
        return None
    path = (path or "").strip() or ""
    param_style = (param_style or "username").strip().lower() or "username"
    return HttpInstagramRapidApiClient(
        api_key=api_key.strip(),
        host=host.strip(),
        path=path,
        param_style=param_style,
    )


def build_rapid_api_client(config: AppConfig):
    """Create Rapid API Instagram client (single provider) if configured."""
    ig = config.instagram
    return _build_one_rapid_client(
        ig.rapidapi_key,
        ig.rapidapi_instagram_host,
        ig.rapidapi_instagram_path or "",
        ig.rapidapi_instagram_param_style or "username",
    )


def build_instagram_stats_provider_client(config: AppConfig):
    """Create stats provider client (single or multi-provider fallback)."""
    ig = config.instagram
    from ugc_bot.infrastructure.instagram.rapid_api_client import (
        MultiProviderInstagramStatsClient,
        SingleProviderWrapper,
    )

    clients_with_ids = []
    # Provider 1 (built but not added to list; uncomment below to enable)
    _ = _build_one_rapid_client(
        ig.rapidapi_key,
        ig.rapidapi_instagram_host,
        ig.rapidapi_instagram_path or "",
        ig.rapidapi_instagram_param_style or "username",
    )
    # if c1:
    #     clients_with_ids.append((c1, "rapid_api"))
    # Provider 2
    c2 = _build_one_rapid_client(
        ig.rapidapi_key_2,
        ig.rapidapi_instagram_host_2,
        ig.rapidapi_instagram_path_2 or "",
        ig.rapidapi_instagram_param_style_2 or "username",
    )
    if c2:
        clients_with_ids.append((c2, "rapid_api_2"))
    # Provider 3
    c3 = _build_one_rapid_client(
        ig.rapidapi_key_3,
        ig.rapidapi_instagram_host_3,
        ig.rapidapi_instagram_path_3 or "",
        ig.rapidapi_instagram_param_style_3 or "username",
    )
    if c3:
        clients_with_ids.append((c3, "rapid_api_3"))
    # Instagram Web Profile API (no key; rate-limited by IP)
    if ig.instagram_web_profile_enabled:
        from ugc_bot.infrastructure.instagram.web_profile_client import (
            InstagramWebProfileClient,
        )

        web_client = InstagramWebProfileClient(
            x_ig_app_id=ig.instagram_web_profile_app_id or "",
        )
        clients_with_ids.append((web_client, "instagram_web"))

    if not clients_with_ids:
        return None
    if len(clients_with_ids) == 1:
        return SingleProviderWrapper(
            clients_with_ids[0][0], clients_with_ids[0][1]
        )
    return MultiProviderInstagramStatsClient(
        clients_with_ids,
        ig.instagram_stats_provider_fallback_delay_seconds,
    )
